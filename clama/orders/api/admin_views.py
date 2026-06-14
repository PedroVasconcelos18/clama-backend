"""
Views admin para pedidos.
"""

from django.db import transaction
from django.db.models import Q
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.generics import ListAPIView, RetrieveAPIView
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from clama.core.api.admin_base import AdminAPIView, AdminGenericAPIView
from clama.core.exceptions import PastoralAPIException
from clama.orders.api.admin_serializers import (
    AdminPedidoDetailSerializer,
    AdminPedidoListSerializer,
)
from clama.orders.models import Pedido, PedidoStatus


class AdminPedidoPagination(LimitOffsetPagination):
    """Paginação para lista de pedidos admin."""

    default_limit = 20
    max_limit = 100


class AdminPedidoListView(AdminGenericAPIView, ListAPIView):
    """
    Lista pedidos com filtros, ordenação e paginação.

    **Filtros disponíveis:**
    - `status`: Status do pedido (ex: PAGO, ERRO). Aceita múltiplos separados por vírgula.
    - `canal`: Canal de entrega (EMAIL, WHATSAPP)
    - `plano`: UUID do plano
    - `created_after`: Data mínima de criação (YYYY-MM-DD)
    - `created_before`: Data máxima de criação (YYYY-MM-DD)
    - `q`: Busca por nome ou email (case-insensitive)

    **Ordenação:**
    - `ordering`: Campo para ordenar (created_at, -created_at, valor_centavos, status)

    **Paginação:**
    - `limit`: Quantidade de resultados (default: 20, max: 100)
    - `offset`: Início da página

    **LGPD:** Este endpoint expõe dados pessoais. Acesso restrito a admins.
    """

    serializer_class = AdminPedidoListSerializer
    pagination_class = AdminPedidoPagination

    def get_queryset(self):
        queryset = Pedido.objects.select_related("plano").order_by("-created_at")

        # Filtro por status (aceita múltiplos separados por vírgula)
        status_param = self.request.query_params.get("status")
        if status_param:
            statuses = [s.strip().lower() for s in status_param.split(",")]
            queryset = queryset.filter(status__in=statuses)

        # Filtro por canal
        canal = self.request.query_params.get("canal")
        if canal:
            queryset = queryset.filter(canal_entrega=canal.lower())

        # Filtro por plano
        plano = self.request.query_params.get("plano")
        if plano:
            queryset = queryset.filter(plano_id=plano)

        # Filtro por data
        created_after = self.request.query_params.get("created_after")
        if created_after:
            queryset = queryset.filter(created_at__date__gte=created_after)

        created_before = self.request.query_params.get("created_before")
        if created_before:
            queryset = queryset.filter(created_at__date__lte=created_before)

        # Filtro por user (usado pela tela admin/customers ao expandir pedidos
        # de um customer especifico).
        user_id = self.request.query_params.get("user_id")
        if user_id:
            queryset = queryset.filter(user_id=user_id)

        # Busca por nome ou email
        q = self.request.query_params.get("q")
        if q:
            queryset = queryset.filter(
                Q(nome__icontains=q) | Q(email__icontains=q)
            )

        # Ordenação
        ordering = self.request.query_params.get("ordering", "-created_at")
        allowed_orderings = ["created_at", "-created_at", "valor_centavos", "-valor_centavos", "status", "-status"]
        if ordering in allowed_orderings:
            queryset = queryset.order_by(ordering)

        return queryset

    @extend_schema(
        tags=["Admin / Pedidos"],
        summary="Listar pedidos",
        description="Lista pedidos com filtros, ordenação e paginação.",
        parameters=[
            OpenApiParameter(name="status", description="Status (PAGO, ERRO, etc). Múltiplos: ERRO,AGUARDANDO_REENVIO"),
            OpenApiParameter(name="canal", description="Canal de entrega (EMAIL, WHATSAPP)"),
            OpenApiParameter(name="plano", description="UUID do plano"),
            OpenApiParameter(name="created_after", description="Data mínima (YYYY-MM-DD)"),
            OpenApiParameter(name="created_before", description="Data máxima (YYYY-MM-DD)"),
            OpenApiParameter(name="q", description="Busca por nome ou email"),
            OpenApiParameter(name="ordering", description="Ordenação (-created_at, valor_centavos, status)"),
            OpenApiParameter(name="limit", description="Itens por página (default: 20, max: 100)"),
            OpenApiParameter(name="offset", description="Offset da paginação"),
        ],
        responses={
            200: AdminPedidoListSerializer(many=True),
            401: OpenApiResponse(description="Não autenticado"),
            403: OpenApiResponse(description="Não é admin"),
        },
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)


class AdminPedidoDetailView(AdminGenericAPIView, RetrieveAPIView):
    """
    Detalhes completos de um pedido.

    **LGPD:** Este endpoint expõe dados pessoais incluindo pedido_oracao e oracao_gerada.
    Acesso restrito a is_clama_admin=True.
    """

    serializer_class = AdminPedidoDetailSerializer
    queryset = Pedido.objects.select_related("plano").prefetch_related("webhook_events")
    lookup_field = "id"

    def get_object(self):
        try:
            return super().get_object()
        except Exception:
            raise PastoralAPIException(
                code="not_found",
                message="Pedido não encontrado",
                pastoral_message="Esse pedido não foi encontrado. Pode ter sido removido?",
                status_code=404,
            )

    @extend_schema(
        tags=["Admin / Pedidos"],
        summary="Detalhes do pedido",
        description="Retorna todos os detalhes de um pedido incluindo dados sensíveis.",
        responses={
            200: AdminPedidoDetailSerializer,
            401: OpenApiResponse(description="Não autenticado"),
            403: OpenApiResponse(description="Não é admin"),
            404: OpenApiResponse(description="Pedido não encontrado"),
        },
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)


class AdminPedidoReenviarView(AdminAPIView):
    """
    Força reenvio manual de um pedido.

    Reseta o status e dispara o envio novamente.
    """

    @extend_schema(
        tags=["Admin / Pedidos"],
        summary="Reenviar pedido",
        description="Força o reenvio da oração para o usuário.",
        responses={
            200: OpenApiResponse(description="Reenvio disparado"),
            401: OpenApiResponse(description="Não autenticado"),
            403: OpenApiResponse(description="Não é admin"),
            404: OpenApiResponse(description="Pedido não encontrado"),
            400: OpenApiResponse(description="Pedido sem oração gerada"),
        },
    )
    def post(self, request, id):
        try:
            pedido = Pedido.objects.get(id=id)
        except Pedido.DoesNotExist:
            raise PastoralAPIException(
                code="not_found",
                message="Pedido não encontrado",
                pastoral_message="Esse pedido não foi encontrado.",
                status_code=404,
            )

        # Pedido travado sem oração (ex.: créditos Anthropic zerados):
        # relança a geração ao invés de só reenviar.
        if not pedido.oracao_gerada:
            regerable_statuses = {PedidoStatus.ERRO, PedidoStatus.AGUARDANDO_REENVIO}
            if pedido.status in regerable_statuses:
                pedido.status = PedidoStatus.PAGO
                pedido.retry_count = 0
                pedido.last_error = ""
                pedido.save(
                    update_fields=["status", "retry_count", "last_error", "updated_at"]
                )

                from clama.prayer_generation.tasks import gerar_oracao_task

                gerar_oracao_task.delay(str(pedido.id))

                return Response(
                    {"status": "ok", "message": "Regeração disparada"},
                    status=status.HTTP_200_OK,
                )

            raise PastoralAPIException(
                code="no_prayer",
                message="Pedido sem oração gerada",
                pastoral_message="Este pedido ainda não tem oração gerada.",
                status_code=400,
            )

        # Reseta status e dispara reenvio
        pedido.status = PedidoStatus.ORACAO_GERADA
        pedido.save(update_fields=["status", "updated_at"])

        # Dispara task de envio
        from clama.notifications.tasks import enviar_oracao_task

        enviar_oracao_task.delay(str(pedido.id))

        return Response(
            {"status": "ok", "message": "Reenvio disparado"},
            status=status.HTTP_200_OK,
        )


class AdminPedidoMarcarGratuitoView(AdminAPIView):
    """
    Marca um pedido como gratuito (fluxo admin).

    Dispensa o pagamento, zera o valor e dispara a geração da oração
    sem passar pelo gateway Asaas. Bloqueado apenas para pedidos já
    enviados (status ENVIADA).
    """

    @extend_schema(
        tags=["Admin / Pedidos"],
        summary="Marcar pedido como gratuito",
        description=(
            "Converte o pedido em gratuito e dispara a geração da oração "
            "(sem pagamento). Recusa pedidos já enviados."
        ),
        responses={
            200: OpenApiResponse(description="Pedido marcado como gratuito"),
            401: OpenApiResponse(description="Não autenticado"),
            403: OpenApiResponse(description="Não é admin"),
            404: OpenApiResponse(description="Pedido não encontrado"),
            409: OpenApiResponse(description="Pedido já enviado"),
        },
    )
    def post(self, request, id):
        try:
            pedido = Pedido.objects.get(id=id)
        except Pedido.DoesNotExist:
            raise PastoralAPIException(
                code="not_found",
                message="Pedido não encontrado",
                pastoral_message="Esse pedido não foi encontrado.",
                status_code=404,
            )

        # Levanta PastoralAPIException 409 se status == ENVIADA.
        disparar = pedido.marcar_como_gratuito()

        if disparar:
            # Import local para evitar circular import (padrão do webhook/reenviar).
            from clama.prayer_generation.tasks import gerar_oracao_task

            pedido_id = str(pedido.id)
            transaction.on_commit(lambda: gerar_oracao_task.delay(pedido_id))

            return Response(
                {
                    "status": "ok",
                    "message": "Pedido marcado como gratuito. Gerando oração.",
                },
                status=status.HTTP_200_OK,
            )

        return Response(
            {"status": "ok", "message": "Pedido já estava marcado como gratuito."},
            status=status.HTTP_200_OK,
        )
