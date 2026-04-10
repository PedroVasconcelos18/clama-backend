"""
Views da API de pagamentos.
"""

import logging

from django.conf import settings
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from clama.core.exceptions import PastoralAPIException
from clama.orders.models import Pedido, PedidoStatus
from clama.payments.exceptions import AsaasIntegrationError
from clama.payments.services.asaas_client import AsaasClient

logger = logging.getLogger("clama.payments.api")


class CheckoutResponseSerializer(serializers.Serializer):
    """Serializer para resposta do checkout."""

    checkout_url = serializers.URLField()
    pedido_id = serializers.UUIDField()


class CheckoutView(APIView):
    """
    Cria cobrança no Asaas e retorna URL de checkout.

    Idempotente em nível de pedido — múltiplas chamadas em pedido
    AGUARDANDO_PAGAMENTO reutilizam ou criam nova cobrança Asaas
    (Epic 3 endurece idempotência).
    """

    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "pedidos_checkout"

    def __init__(self, client: AsaasClient | None = None, **kwargs):
        """
        Inicializa a view com cliente Asaas injetável para testes.

        Args:
            client: Instância de AsaasClient (opcional, para testes)
        """
        super().__init__(**kwargs)
        self._client = client

    @property
    def client(self) -> AsaasClient:
        """Retorna cliente Asaas, criando se necessário."""
        if self._client is None:
            self._client = AsaasClient()
        return self._client

    def _get_pedido(self, pedido_id: str) -> Pedido:
        """
        Busca pedido por ID ou levanta 404.

        Args:
            pedido_id: UUID do pedido

        Returns:
            Pedido encontrado

        Raises:
            PastoralAPIException: Se pedido não existir (404)
        """
        try:
            return Pedido.objects.get(id=pedido_id)
        except Pedido.DoesNotExist:
            raise PastoralAPIException(
                code="not_found",
                message="Pedido não encontrado",
                pastoral_message="Não encontramos esse pedido. Verifique se o link está correto.",
                status_code=404,
            )

    def _validate_status_for_checkout(self, pedido: Pedido) -> None:
        """
        Valida se o pedido pode fazer checkout.

        Args:
            pedido: Pedido a validar

        Raises:
            PastoralAPIException: Se pedido já foi pago (409)
        """
        if pedido.status != PedidoStatus.AGUARDANDO_PAGAMENTO:
            raise PastoralAPIException(
                code="pedido_ja_pago",
                message="Pedido já foi pago ou processado",
                pastoral_message="Esse pedido já foi pago, vamos te encaminhar para a confirmação.",
                status_code=409,
            )

    @extend_schema(
        tags=["Pedidos"],
        summary="Criar checkout de pagamento",
        description="""
Cria uma cobrança no Asaas e retorna a URL de checkout.

**Idempotência:** Múltiplas chamadas em pedido com status AGUARDANDO_PAGAMENTO
criam nova cobrança ou reutilizam existente (Epic 3 endurece idempotência).

**Status permitido:** Apenas AGUARDANDO_PAGAMENTO. Pedidos já pagos retornam 409.

**Tipos de pagamento:** Pix, Boleto e Cartão de Crédito são aceitos.
        """,
        responses={
            200: OpenApiResponse(
                response=CheckoutResponseSerializer,
                description="URL de checkout criada com sucesso",
            ),
            404: OpenApiResponse(description="Pedido não encontrado"),
            409: OpenApiResponse(description="Pedido já foi pago"),
            502: OpenApiResponse(description="Erro de integração com Asaas"),
        },
    )
    def post(self, request, id):
        """
        Cria cobrança no Asaas e retorna URL de checkout.

        Args:
            request: Request HTTP
            id: UUID do pedido

        Returns:
            Response com checkout_url e pedido_id
        """
        # 1. Busca pedido
        pedido = self._get_pedido(id)

        # 2. Valida status
        self._validate_status_for_checkout(pedido)

        try:
            # 3. Cria cliente no Asaas
            customer_data = self.client.criar_cliente(
                nome=pedido.nome,
                email=pedido.email,
            )
            customer_id = customer_data["id"]

            # 4. Cria cobrança
            # Descrição curta sem PII
            descricao = f"Pedido Clama #{str(pedido.id)[:8]}"

            charge_data = self.client.criar_cobranca(
                customer_id=customer_id,
                valor_centavos=pedido.valor_centavos,
                descricao=descricao,
                pedido_id=str(pedido.id),
            )

            # 5. Persiste IDs no pedido
            pedido.asaas_charge_id = charge_data["id"]
            pedido.asaas_invoice_url = charge_data.get("invoiceUrl", "")
            pedido.save(update_fields=["asaas_charge_id", "asaas_invoice_url", "updated_at"])

            logger.info(
                "Checkout created",
                extra={
                    "event": "checkout_created",
                    "pedido_id": str(pedido.id),
                    "charge_id": charge_data["id"],
                },
            )

            # 6. Retorna URL de checkout
            return Response(
                {
                    "checkout_url": charge_data.get("invoiceUrl", ""),
                    "pedido_id": str(pedido.id),
                },
                status=status.HTTP_200_OK,
            )

        except AsaasIntegrationError as e:
            logger.error(
                "Checkout failed",
                extra={
                    "event": "checkout_failed",
                    "pedido_id": str(pedido.id),
                    "error": str(e),
                },
            )
            raise PastoralAPIException(
                code=e.code,
                message=e.message,
                pastoral_message=e.pastoral_message,
                status_code=502,
            )
