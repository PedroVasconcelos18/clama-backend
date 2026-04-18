"""
Views admin para gestão de documentos de contexto.
"""

import logging

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from clama.core.api.admin_base import AdminGenericAPIView
from clama.documents.api.serializers import (
    AdminDocumentoContextoListSerializer,
    AdminDocumentoContextoSerializer,
)
from clama.documents.models import DocumentoContexto
from clama.documents.services.anthropic_files import (
    AnthropicFilesError,
    deletar_arquivo_anthropic,
    sincronizar_documento,
)

logger = logging.getLogger("clama.documents.admin_views")


class AdminDocumentoContextoViewSet(AdminGenericAPIView, ModelViewSet):
    """
    CRUD de documentos de contexto para admin.

    **Operações:**
    - GET /api/admin/documentos/ - Lista todos os documentos
    - GET /api/admin/documentos/{id}/ - Detalhes de um documento
    - POST /api/admin/documentos/ - Upload de novo documento
    - PATCH /api/admin/documentos/{id}/ - Atualiza nome/descrição/ativo
    - DELETE /api/admin/documentos/{id}/ - Remove documento (local e Anthropic)
    - POST /api/admin/documentos/{id}/sincronizar/ - Sincroniza com Anthropic

    **Upload:**
    - Use multipart/form-data para enviar o arquivo
    - Formatos aceitos: PDF, texto plano
    - Limite: 100MB

    **Sincronização:**
    - Documentos são criados localmente primeiro
    - Use /sincronizar/ para enviar para a Anthropic
    - Status de sincronização visível em `esta_sincronizado`
    """

    queryset = DocumentoContexto.objects.all().order_by("-created_at")
    lookup_field = "id"
    parser_classes = [MultiPartParser, FormParser]

    def get_serializer_class(self):
        """Usa serializer simplificado para listagem."""
        if self.action == "list":
            return AdminDocumentoContextoListSerializer
        return AdminDocumentoContextoSerializer

    @extend_schema(
        tags=["Admin / Documentos"],
        summary="Listar documentos de contexto",
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(
        tags=["Admin / Documentos"],
        summary="Detalhes do documento",
    )
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)

    @extend_schema(
        tags=["Admin / Documentos"],
        summary="Upload de documento",
        description="""
Faz upload de um novo documento de contexto.

**Formatos aceitos:** PDF (application/pdf), texto plano (text/plain)
**Limite:** 100MB

O documento é criado localmente. Use `/sincronizar/` para enviar para a Anthropic.

**Campos:**
- `nome` (obrigatório): Nome identificador
- `descricao` (opcional): Descrição do conteúdo
- `arquivo` (obrigatório): Arquivo PDF ou texto
- `ativo` (opcional, default true): Se será usado no contexto
        """,
        request=AdminDocumentoContextoSerializer,
        responses={
            201: AdminDocumentoContextoSerializer,
            400: OpenApiResponse(description="Validação falhou"),
            401: OpenApiResponse(description="Não autenticado"),
            403: OpenApiResponse(description="Não é admin"),
        },
    )
    def create(self, request, *args, **kwargs):
        return super().create(request, *args, **kwargs)

    @extend_schema(
        tags=["Admin / Documentos"],
        summary="Atualizar documento",
        description="""
Atualiza metadados do documento.

**Campos editáveis:** nome, descricao, ativo

**Nota:** Não é possível trocar o arquivo. Delete e crie novo.
        """,
    )
    def partial_update(self, request, *args, **kwargs):
        return super().partial_update(request, *args, **kwargs)

    @extend_schema(
        tags=["Admin / Documentos"],
        summary="Deletar documento",
        description="""
Remove o documento da Anthropic e do banco local.

**Importante:** Se o documento estiver sincronizado, a deleção na Anthropic
deve ser bem sucedida antes de remover localmente. Isso garante que não
fiquem arquivos órfãos na Anthropic sem referência local.
        """,
        responses={
            204: OpenApiResponse(description="Documento removido"),
            401: OpenApiResponse(description="Não autenticado"),
            403: OpenApiResponse(description="Não é admin"),
            404: OpenApiResponse(description="Documento não encontrado"),
            500: OpenApiResponse(description="Erro ao deletar na Anthropic"),
        },
    )
    def destroy(self, request, *args, **kwargs):
        documento = self.get_object()

        # Se sincronizado, deve deletar na Anthropic primeiro
        if documento.anthropic_file_id:
            try:
                deletar_arquivo_anthropic(documento.anthropic_file_id)
                logger.info(
                    "Arquivo deletado na Anthropic",
                    extra={
                        "event": "documento_delete_anthropic_success",
                        "documento_id": str(documento.id),
                        "file_id": documento.anthropic_file_id,
                    },
                )
            except AnthropicFilesError as e:
                logger.error(
                    "Erro ao deletar arquivo na Anthropic",
                    extra={
                        "event": "documento_delete_anthropic_error",
                        "documento_id": str(documento.id),
                        "file_id": documento.anthropic_file_id,
                        "error": str(e),
                    },
                )
                return Response(
                    {
                        "status": "error",
                        "message": f"Falha ao remover da Anthropic: {e}. Documento não foi removido.",
                    },
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

        return super().destroy(request, *args, **kwargs)

    @action(detail=True, methods=["post"])
    @extend_schema(
        tags=["Admin / Documentos"],
        summary="Toggle ativo",
        description="""
Ativa ou desativa o documento.

**Ao ativar:** Se o documento ainda não foi sincronizado com a Anthropic,
a sincronização é feita automaticamente.

**Ao desativar:** O documento deixa de ser usado no contexto das orações,
mas o arquivo permanece na Anthropic para reativação futura.
        """,
        request=None,
        responses={
            200: OpenApiResponse(description="Status alterado"),
            401: OpenApiResponse(description="Não autenticado"),
            403: OpenApiResponse(description="Não é admin"),
            404: OpenApiResponse(description="Documento não encontrado"),
            500: OpenApiResponse(description="Erro na sincronização"),
        },
    )
    def toggle_ativo(self, request, id=None):
        documento = self.get_object()
        novo_status = not documento.ativo

        # Se está ativando e ainda não sincronizou, sincroniza agora
        if novo_status and not documento.anthropic_file_id:
            try:
                documento = sincronizar_documento(documento)
                logger.info(
                    "Documento sincronizado ao ativar",
                    extra={
                        "event": "documento_sincronizado_ao_ativar",
                        "documento_id": str(documento.id),
                        "file_id": documento.anthropic_file_id,
                    },
                )
            except AnthropicFilesError as e:
                logger.error(
                    "Erro ao sincronizar documento ao ativar",
                    extra={
                        "event": "documento_sincronizacao_error",
                        "documento_id": str(documento.id),
                        "error": str(e),
                    },
                )
                return Response(
                    {
                        "status": "error",
                        "message": f"Falha ao sincronizar com Anthropic: {e}",
                    },
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

        documento.ativo = novo_status
        documento.save(update_fields=["ativo", "updated_at"])

        status_text = "ativado" if documento.ativo else "desativado"

        return Response(
            {
                "status": "ok",
                "message": f"Documento '{documento.nome}' {status_text}.",
                "ativo": documento.ativo,
                "file_id": documento.anthropic_file_id,
            },
            status=status.HTTP_200_OK,
        )
