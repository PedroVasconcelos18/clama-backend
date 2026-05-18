"""
Admin endpoint pra lista de customers (users do Clama) com counts de pedidos,
flag de ban e dados pra moderacao do blog.

Reaproveita endpoints de banimento ja existentes em `clama.blog.urls`
(`/api/blog/admin/banned-customers/`) — esta view so adiciona o lado de
LISTAGEM (que estava no gap).
"""

from django.db.models import Count, OuterRef, Q, Subquery
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import serializers
from rest_framework.generics import ListAPIView, RetrieveAPIView
from rest_framework.pagination import LimitOffsetPagination

from clama.blog.models import CustomerBanido
from clama.core.api.admin_base import AdminGenericAPIView
from clama.core.exceptions import PastoralAPIException
from clama_backend.users.models import User


class AdminCustomerListSerializer(serializers.ModelSerializer):
    """Lista compacta — sem dados sensiveis decryptografados (cpf/telefone).

    Email NAO eh encrypted no model `users.User` (vide schema) e eh seguro
    pra UI admin. Counts vem de annotate, ban info de subquery.
    """

    total_pedidos = serializers.IntegerField(read_only=True)
    pedidos_pagos = serializers.IntegerField(read_only=True)
    pedidos_gratuitos = serializers.IntegerField(read_only=True)
    total_comentarios = serializers.IntegerField(read_only=True)
    is_banned = serializers.BooleanField(read_only=True)
    motivo_ban = serializers.CharField(read_only=True, allow_null=True)
    banido_em = serializers.DateTimeField(read_only=True, allow_null=True)

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "nome_completo",
            "date_joined",
            "freemium_used_at",
            "is_clama_admin",
            "total_pedidos",
            "pedidos_pagos",
            "pedidos_gratuitos",
            "total_comentarios",
            "is_banned",
            "motivo_ban",
            "banido_em",
        ]
        read_only_fields = fields


class AdminCustomerPagination(LimitOffsetPagination):
    default_limit = 20
    max_limit = 100


class AdminCustomerListView(AdminGenericAPIView, ListAPIView):
    """Lista todos os customers do Clama (paginada, com busca/filtros).

    Filtros:
    - `q`: case-insensitive em email/nome_completo
    - `banned`: "true" → so banidos ativos; "false" → so nao-banidos
    - `freemium`: "true" → so quem ja usou freemium; "false" → ainda nao

    Counts retornados:
    - `total_pedidos`: todos os pedidos vinculados ao user
    - `pedidos_pagos`: pedidos status pago/enviada/etc nao-gratuitos
    - `pedidos_gratuitos`: pedidos eh_gratuito=True
    - `total_comentarios`: comentarios no blog
    """

    serializer_class = AdminCustomerListSerializer
    pagination_class = AdminCustomerPagination

    def get_queryset(self):
        # Subquery do banimento ATIVO (revogado_em is null) — pega o mais
        # recente caso multiplos (defensivo; constraint nao impede).
        ban_ativo = CustomerBanido.objects.filter(
            customer=OuterRef("pk"), revogado_em__isnull=True
        ).order_by("-banido_em")

        qs = (
            User.objects.all()
            .annotate(
                total_pedidos=Count("pedidos", distinct=True),
                pedidos_pagos=Count(
                    "pedidos",
                    filter=Q(pedidos__eh_gratuito=False),
                    distinct=True,
                ),
                pedidos_gratuitos=Count(
                    "pedidos",
                    filter=Q(pedidos__eh_gratuito=True),
                    distinct=True,
                ),
                total_comentarios=Count("comentarios_blog", distinct=True),
                motivo_ban=Subquery(ban_ativo.values("motivo")[:1]),
                banido_em=Subquery(ban_ativo.values("banido_em")[:1]),
            )
            .annotate(is_banned=Q(motivo_ban__isnull=False))
            .order_by("-date_joined")
        )

        q = self.request.query_params.get("q", "").strip()
        if q:
            qs = qs.filter(Q(email__icontains=q) | Q(nome_completo__icontains=q))

        banned = self.request.query_params.get("banned")
        if banned == "true":
            qs = qs.filter(motivo_ban__isnull=False)
        elif banned == "false":
            qs = qs.filter(motivo_ban__isnull=True)

        freemium = self.request.query_params.get("freemium")
        if freemium == "true":
            qs = qs.filter(freemium_used_at__isnull=False)
        elif freemium == "false":
            qs = qs.filter(freemium_used_at__isnull=True)

        return qs

    @extend_schema(
        tags=["Admin / Customers"],
        summary="Listar customers",
        description=(
            "Lista todos os customers com counts de pedidos, comentarios e "
            "flag de banimento ativo."
        ),
        parameters=[
            OpenApiParameter(name="q", description="Busca por email ou nome"),
            OpenApiParameter(name="banned", description='"true" | "false"'),
            OpenApiParameter(name="freemium", description='"true" | "false"'),
            OpenApiParameter(name="limit", description="Default 20, max 100"),
            OpenApiParameter(name="offset", description="Offset paginacao"),
        ],
        responses={
            200: AdminCustomerListSerializer(many=True),
            401: OpenApiResponse(description="Nao autenticado"),
            403: OpenApiResponse(description="Nao eh admin"),
        },
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)


class CustomerBanimentoHistoricoSerializer(serializers.ModelSerializer):
    banido_por_email = serializers.EmailField(
        source="banido_por.email", read_only=True
    )
    revogado_por_email = serializers.EmailField(
        source="revogado_por.email", read_only=True, allow_null=True
    )

    class Meta:
        model = CustomerBanido
        fields = [
            "id",
            "motivo",
            "banido_em",
            "banido_por_email",
            "revogado_em",
            "revogado_por_email",
        ]


class AdminCustomerDetailSerializer(serializers.ModelSerializer):
    """Detalhe completo do customer pra modal admin.

    Inclui dados criptografados (CPF/telefone) decryptografados pelo ORM, hashes
    pra debug do gate freemium, contagens e historico COMPLETO de banimentos
    (ativos + revogados).
    """

    total_pedidos = serializers.IntegerField(read_only=True)
    pedidos_pagos = serializers.IntegerField(read_only=True)
    pedidos_gratuitos = serializers.IntegerField(read_only=True)
    total_comentarios = serializers.IntegerField(read_only=True)
    is_banned = serializers.SerializerMethodField()
    banimentos = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "nome_completo",
            "date_joined",
            "last_login",
            "is_active",
            "is_clama_admin",
            "cpf_cnpj",
            "telefone",
            "nome_format_blog",
            "freemium_used_at",
            "total_pedidos",
            "pedidos_pagos",
            "pedidos_gratuitos",
            "total_comentarios",
            "is_banned",
            "banimentos",
        ]
        read_only_fields = fields

    def get_is_banned(self, obj: User) -> bool:
        return obj.banimentos.filter(revogado_em__isnull=True).exists()

    def get_banimentos(self, obj: User) -> list[dict]:
        qs = obj.banimentos.all().order_by("-banido_em").select_related(
            "banido_por", "revogado_por"
        )
        return CustomerBanimentoHistoricoSerializer(qs, many=True).data


class AdminCustomerDetailView(AdminGenericAPIView, RetrieveAPIView):
    """`GET /api/admin/customers/<id>/` — detalhe completo pra modal."""

    serializer_class = AdminCustomerDetailSerializer
    lookup_field = "id"

    def get_queryset(self):
        return User.objects.annotate(
            total_pedidos=Count("pedidos", distinct=True),
            pedidos_pagos=Count(
                "pedidos",
                filter=Q(pedidos__eh_gratuito=False),
                distinct=True,
            ),
            pedidos_gratuitos=Count(
                "pedidos",
                filter=Q(pedidos__eh_gratuito=True),
                distinct=True,
            ),
            total_comentarios=Count("comentarios_blog", distinct=True),
        )

    def get_object(self):
        try:
            return super().get_object()
        except Exception:
            raise PastoralAPIException(
                code="not_found",
                message="Customer nao encontrado",
                pastoral_message="Esse customer nao foi encontrado.",
                status_code=404,
            )

    @extend_schema(
        tags=["Admin / Customers"],
        summary="Detalhe do customer",
        responses={
            200: AdminCustomerDetailSerializer,
            401: OpenApiResponse(description="Nao autenticado"),
            403: OpenApiResponse(description="Nao eh admin"),
            404: OpenApiResponse(description="Nao encontrado"),
        },
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)
