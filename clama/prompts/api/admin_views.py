"""
Views admin para prompts.
"""

from django.db.models import Max
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.viewsets import ModelViewSet

from clama.core.api.admin_base import AdminGenericAPIView
from clama.prompts.models import PromptTemplate


class AdminPromptTemplateSerializer(serializers.ModelSerializer):
    """
    Serializer para CRUD de prompts no admin.

    VERSIONAMENTO:
    - Cada edição cria uma nova versão
    - Versão é auto-incrementada baseada no nome
    - Templates são criados inativos por padrão
    - Use /ativar/ para ativar uma versão específica
    """

    class Meta:
        model = PromptTemplate
        fields = [
            "id",
            "nome",
            "versao",
            "system_prompt",
            "instrucoes_por_complexidade",
            "ativo",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "versao", "ativo", "created_at", "updated_at"]

    def create(self, validated_data):
        # Auto-incrementa versão baseada no nome
        nome = validated_data["nome"]
        max_versao = PromptTemplate.objects.filter(nome=nome).aggregate(
            max_v=Max("versao")
        )["max_v"]
        validated_data["versao"] = (max_versao or 0) + 1
        validated_data["ativo"] = False  # Sempre cria inativo
        return super().create(validated_data)


class PreviewRequestSerializer(serializers.Serializer):
    """Serializer para request de preview de prompt."""

    pedido_exemplo = serializers.DictField(
        child=serializers.CharField(),
        help_text="Dados do pedido exemplo: {nome, sexo, pedido_oracao, plano_complexidade}",
    )


class AdminPromptTemplateViewSet(AdminGenericAPIView, ModelViewSet):
    """
    CRUD de prompts para admin.

    **Versionamento:** Cada save cria nova versão. Não é possível editar ou deletar.

    **Operações:**
    - GET /api/admin/prompts/ - Lista todos os templates
    - GET /api/admin/prompts/{id}/ - Detalhes de um template
    - POST /api/admin/prompts/ - Cria nova versão
    - POST /api/admin/prompts/{id}/ativar/ - Ativa esta versão (desativa outras)
    - POST /api/admin/prompts/{id}/preview/ - Testa geração sem persistir

    **Não há UPDATE nem DELETE** - Cada edição cria nova versão para auditoria.
    """

    serializer_class = AdminPromptTemplateSerializer
    queryset = PromptTemplate.objects.all().order_by("-versao")
    lookup_field = "id"

    # Apenas list, retrieve, create
    http_method_names = ["get", "post", "head", "options"]

    @extend_schema(
        tags=["Admin / Prompts"],
        summary="Listar prompts",
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(
        tags=["Admin / Prompts"],
        summary="Detalhes do prompt",
    )
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)

    @extend_schema(
        tags=["Admin / Prompts"],
        summary="Criar nova versão",
        description="""
Cria uma nova versão do prompt.

A versão é auto-incrementada baseada no nome.
O template é criado inativo por padrão - use /ativar/ para ativá-lo.

**Nota:** Editar prompts é versionado. Cada save cria nova versão.
        """,
    )
    def create(self, request, *args, **kwargs):
        return super().create(request, *args, **kwargs)

    @action(detail=True, methods=["post"])
    @extend_schema(
        tags=["Admin / Prompts"],
        summary="Ativar prompt",
        description="Ativa esta versão do prompt. Desativa automaticamente as outras.",
        responses={
            200: OpenApiResponse(description="Prompt ativado"),
            401: OpenApiResponse(description="Não autenticado"),
            403: OpenApiResponse(description="Não é admin"),
            404: OpenApiResponse(description="Prompt não encontrado"),
        },
    )
    def ativar(self, request, id=None):
        template = self.get_object()
        template.ativo = True
        template.save()  # O save() já desativa os outros
        return Response(
            {"status": "ok", "message": f"Prompt {template.nome} v{template.versao} ativado"},
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=["post"], throttle_classes=[ScopedRateThrottle])
    @extend_schema(
        tags=["Admin / Prompts"],
        summary="Preview de prompt",
        description="""
Testa a geração de oração com este template sem persistir.

Recebe dados de exemplo e retorna a oração que seria gerada.

**Rate limit:** 5 calls/minuto (consome créditos do Claude).
        """,
        request=PreviewRequestSerializer,
        responses={
            200: OpenApiResponse(description="Oração gerada para preview"),
            400: OpenApiResponse(description="Dados inválidos"),
            401: OpenApiResponse(description="Não autenticado"),
            403: OpenApiResponse(description="Não é admin"),
            404: OpenApiResponse(description="Prompt não encontrado"),
            429: OpenApiResponse(description="Rate limit excedido"),
        },
    )
    def preview(self, request, id=None):
        template = self.get_object()

        serializer = PreviewRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        pedido_exemplo = serializer.validated_data["pedido_exemplo"]

        # Cria um pedido fake para o prompt builder
        from clama.prayer_generation.exceptions import InsufficientCreditsError
        from clama.prayer_generation.services.anthropic_client import AnthropicClient
        from clama.prayer_generation.services.prompt_builder import build_prompt_for_preview

        try:
            system_prompt, user_message = build_prompt_for_preview(
                nome=pedido_exemplo.get("nome", "Maria"),
                sexo=pedido_exemplo.get("sexo", "feminino"),
                pedido_oracao=pedido_exemplo.get("pedido_oracao", "Oração de teste"),
                plano_complexidade=pedido_exemplo.get("plano_complexidade", "simples"),
                template=template,
            )

            # Gera oração
            client = AnthropicClient()
            nome = pedido_exemplo.get("nome", "Maria")
            oracao = client._generate_raw(system_prompt, user_message, nome=nome)

            return Response({
                "oracao_preview": oracao,
                "template": {
                    "id": str(template.id),
                    "nome": template.nome,
                    "versao": template.versao,
                },
            })

        except InsufficientCreditsError:
            return Response(
                {
                    "error": {
                        "code": "anthropic_no_credits",
                        "message": (
                            "A API da Anthropic está sem créditos. "
                            "Recarregue os créditos para gerar previews."
                        ),
                    }
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except Exception as exc:
            return Response(
                {"error": {"message": str(exc)}},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    # Override to set throttle scope for preview
    def get_throttle_scope(self):
        if self.action == "preview":
            return "admin_login"  # Reutiliza o throttle de 5/min
        return None
