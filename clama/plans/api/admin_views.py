"""
Views admin para planos.
"""

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from clama.core.api.admin_base import AdminGenericAPIView
from clama.plans.models import Complexidade, Plan


class AdminPlanSerializer(serializers.ModelSerializer):
    """
    Serializer para CRUD de planos no admin.

    Validações:
    - valor_centavos >= 2000 (R$ 20,00)
    - complexidade deve ser um valor válido
    - nome deve ser único entre planos ativos

    IMPORTANTE: Editar valor_centavos ou complexidade de um plano
    NÃO afeta pedidos já criados (eles têm snapshot em Pedido.valor_centavos).
    """

    valor_reais_str = serializers.CharField(read_only=True)

    class Meta:
        model = Plan
        fields = [
            "id",
            "nome",
            "valor_centavos",
            "valor_reais_str",
            "descricao",
            "complexidade",
            "ordem",
            "ativo",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at", "valor_reais_str"]

    def validate_valor_centavos(self, value):
        if value < 2000:
            raise serializers.ValidationError("Valor mínimo é R$ 20,00 (2000 centavos)")
        return value

    def validate_complexidade(self, value):
        valid_choices = [c[0] for c in Complexidade.choices]
        if value not in valid_choices:
            raise serializers.ValidationError(
                f"Complexidade inválida. Valores válidos: {valid_choices}"
            )
        return value

    def validate(self, attrs):
        # Valida nome único entre ativos
        nome = attrs.get("nome")
        ativo = attrs.get("ativo", True)
        instance = self.instance

        if nome and ativo:
            queryset = Plan.objects.filter(nome=nome, ativo=True)
            if instance:
                queryset = queryset.exclude(pk=instance.pk)
            if queryset.exists():
                raise serializers.ValidationError(
                    {"nome": "Já existe um plano ativo com este nome."}
                )

        return attrs


class AdminPlanViewSet(AdminGenericAPIView, ModelViewSet):
    """
    CRUD de planos para admin.

    **Operações:**
    - GET /api/admin/planos/ - Lista todos os planos
    - GET /api/admin/planos/{id}/ - Detalhes de um plano
    - POST /api/admin/planos/ - Cria novo plano
    - PUT /api/admin/planos/{id}/ - Atualiza plano completo
    - PATCH /api/admin/planos/{id}/ - Atualiza parcialmente
    - POST /api/admin/planos/{id}/desativar/ - Desativa plano (soft delete)

    **Não há DELETE** - Use desativar para remover da lista pública.

    **IMPORTANTE:** Editar valor_centavos ou complexidade de um plano
    NÃO afeta pedidos já criados (eles têm snapshot em Pedido.valor_centavos).
    """

    serializer_class = AdminPlanSerializer
    queryset = Plan.objects.all().order_by("ordem")
    lookup_field = "id"

    # Remove destroy action - usamos soft delete
    http_method_names = ["get", "post", "put", "patch", "head", "options"]

    @extend_schema(
        tags=["Admin / Planos"],
        summary="Listar planos",
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(
        tags=["Admin / Planos"],
        summary="Detalhes do plano",
    )
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)

    @extend_schema(
        tags=["Admin / Planos"],
        summary="Criar plano",
    )
    def create(self, request, *args, **kwargs):
        return super().create(request, *args, **kwargs)

    @extend_schema(
        tags=["Admin / Planos"],
        summary="Atualizar plano",
    )
    def update(self, request, *args, **kwargs):
        return super().update(request, *args, **kwargs)

    @extend_schema(
        tags=["Admin / Planos"],
        summary="Atualizar parcialmente",
    )
    def partial_update(self, request, *args, **kwargs):
        return super().partial_update(request, *args, **kwargs)

    @action(detail=True, methods=["post"])
    @extend_schema(
        tags=["Admin / Planos"],
        summary="Desativar plano",
        description="Desativa o plano (soft delete). O plano não aparece mais para usuárias mas continua no histórico.",
        responses={
            200: OpenApiResponse(description="Plano desativado"),
            401: OpenApiResponse(description="Não autenticado"),
            403: OpenApiResponse(description="Não é admin"),
            404: OpenApiResponse(description="Plano não encontrado"),
        },
    )
    def desativar(self, request, id=None):
        plan = self.get_object()
        plan.ativo = False
        plan.save(update_fields=["ativo", "updated_at"])
        return Response(
            {"status": "ok", "message": "Plano desativado"},
            status=status.HTTP_200_OK,
        )
