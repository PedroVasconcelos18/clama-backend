"""
Views admin para instituições.
"""

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from clama.core.api.admin_base import AdminGenericAPIView
from clama.instituicoes.api.serializers import AdminInstituicaoSerializer
from clama.instituicoes.models import Instituicao


class AdminInstituicaoViewSet(AdminGenericAPIView, ModelViewSet):
    """
    CRUD de instituições para admin.

    **Operações:**
    - GET /api/admin/instituicoes/ - Lista todas as instituições
    - GET /api/admin/instituicoes/{id}/ - Detalhes de uma instituição
    - POST /api/admin/instituicoes/ - Cria nova instituição
    - PUT /api/admin/instituicoes/{id}/ - Atualiza completa
    - PATCH /api/admin/instituicoes/{id}/ - Atualiza parcialmente
    - POST /api/admin/instituicoes/{id}/desativar/ - Desativa (soft delete)

    **Não há DELETE** - Use desativar para remover do dropdown público.
    Repasses já registrados a uma instituição desativada ficam intactos.
    """

    serializer_class = AdminInstituicaoSerializer
    queryset = Instituicao.objects.all().order_by("ordem", "nome")
    lookup_field = "id"
    # JSON (toggle ativo/PATCH) + multipart (upload da logo).
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    # Remove destroy action - usamos soft delete
    http_method_names = ["get", "post", "put", "patch", "head", "options"]

    @extend_schema(
        tags=["Admin / Instituições"],
        summary="Listar instituições",
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(
        tags=["Admin / Instituições"],
        summary="Detalhes da instituição",
    )
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)

    @extend_schema(
        tags=["Admin / Instituições"],
        summary="Criar instituição",
    )
    def create(self, request, *args, **kwargs):
        return super().create(request, *args, **kwargs)

    @extend_schema(
        tags=["Admin / Instituições"],
        summary="Atualizar instituição",
    )
    def update(self, request, *args, **kwargs):
        return super().update(request, *args, **kwargs)

    @extend_schema(
        tags=["Admin / Instituições"],
        summary="Atualizar parcialmente",
    )
    def partial_update(self, request, *args, **kwargs):
        return super().partial_update(request, *args, **kwargs)

    @action(detail=True, methods=["post"])
    @extend_schema(
        tags=["Admin / Instituições"],
        summary="Desativar instituição",
        description="Desativa a instituição (soft delete). Some do dropdown público; repasses já registrados ficam intactos.",
        responses={
            200: OpenApiResponse(description="Instituição desativada"),
            401: OpenApiResponse(description="Não autenticado"),
            403: OpenApiResponse(description="Não é admin"),
            404: OpenApiResponse(description="Instituição não encontrada"),
        },
    )
    def desativar(self, request, id=None):
        instituicao = self.get_object()
        instituicao.ativo = False
        instituicao.save(update_fields=["ativo", "updated_at"])
        return Response(
            {"status": "ok", "message": "Instituição desativada"},
            status=status.HTTP_200_OK,
        )
