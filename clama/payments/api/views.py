"""
Views da API de pagamentos.
"""

import logging

from django.conf import settings
from django.db import transaction
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

    def _get_pedido_locked(self, pedido_id: str) -> Pedido:
        """
        Busca pedido por ID com lock pessimista (SELECT FOR UPDATE).

        Deve ser chamado dentro de uma transação. O lock é liberado no commit/rollback
        e serializa requests concorrentes no MESMO pedido (double-click, retries do front),
        prevenindo criação de cobranças duplicadas na Asaas.

        Args:
            pedido_id: UUID do pedido

        Returns:
            Pedido encontrado, com lock de linha ativo até o fim da transação.

        Raises:
            PastoralAPIException: Se pedido não existir (404)
        """
        try:
            return Pedido.objects.select_for_update().get(id=pedido_id)
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

    def _validate_pedido_data(self, pedido: Pedido) -> None:
        """
        Valida dados do pedido exigidos pela Asaas antes de chamar a API.

        Falha rápido com 422 em vez de delegar à Asaas e receber um 400
        genérico que quebraria o fluxo.

        Raises:
            PastoralAPIException: Se dados obrigatórios estiverem ausentes (422).
        """
        if not pedido.cpf_cnpj:
            raise PastoralAPIException(
                code="cpf_cnpj_obrigatorio",
                message="CPF/CNPJ é obrigatório para gerar a cobrança",
                pastoral_message=(
                    "Precisamos do seu CPF para gerar a cobrança. "
                    "Volte ao formulário e complete o cadastro."
                ),
                status_code=422,
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
            422: OpenApiResponse(description="Dados do pedido inválidos ou rejeitados pela Asaas"),
            503: OpenApiResponse(description="Asaas indisponível após retries"),
        },
    )
    def post(self, request, id):
        """
        Cria cobrança no Asaas e retorna URL de checkout.

        Idempotente: requests concorrentes ou repetidas no mesmo pedido reutilizam
        a cobrança existente em vez de criar duplicadas na Asaas.

        Args:
            request: Request HTTP
            id: UUID do pedido

        Returns:
            Response com checkout_url e pedido_id
        """
        # A transação serializa requests concorrentes no mesmo pedido via
        # SELECT FOR UPDATE. O lock é mantido durante a chamada à Asaas
        # (≤30s com retries) — aceitável porque é escopo de pedido único.
        with transaction.atomic():
            pedido = self._get_pedido_locked(id)
            self._validate_status_for_checkout(pedido)
            self._validate_pedido_data(pedido)

            # Idempotência: cobrança já criada → reutiliza.
            # A segunda request concorrente vê este estado após o lock liberar.
            if pedido.asaas_charge_id and pedido.asaas_invoice_url:
                logger.info(
                    "Checkout reused",
                    extra={
                        "event": "checkout_reused",
                        "pedido_id": str(pedido.id),
                        "charge_id": pedido.asaas_charge_id,
                    },
                )
                return Response(
                    {
                        "checkout_url": pedido.asaas_invoice_url,
                        "pedido_id": str(pedido.id),
                    },
                    status=status.HTTP_200_OK,
                )

            try:
                customer_data = self.client.criar_cliente(
                    nome=pedido.nome,
                    email=pedido.email,
                    cpf_cnpj=pedido.cpf_cnpj,
                )
                customer_id = customer_data["id"]

                # Descrição curta sem PII
                descricao = f"Pedido Clama #{str(pedido.id)[:8]}"

                charge_data = self.client.criar_cobranca(
                    customer_id=customer_id,
                    valor_centavos=pedido.valor_centavos,
                    descricao=descricao,
                    pedido_id=str(pedido.id),
                )

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

                return Response(
                    {
                        "checkout_url": charge_data.get("invoiceUrl", ""),
                        "pedido_id": str(pedido.id),
                    },
                    status=status.HTTP_200_OK,
                )

            except AsaasIntegrationError as e:
                # 4xx da Asaas = dados rejeitados (422). Rede/timeout/5xx = upstream fora (503).
                # Usar 502 aqui quebra CORS: a Cloudflare substitui o body pela própria página de erro.
                if e.upstream_status is not None and 400 <= e.upstream_status < 500:
                    response_status = 422
                else:
                    response_status = 503

                logger.error(
                    "Checkout failed",
                    extra={
                        "event": "checkout_failed",
                        "pedido_id": str(pedido.id),
                        "error": str(e),
                        "upstream_status": e.upstream_status,
                        "upstream_body": e.upstream_body,
                    },
                )
                raise PastoralAPIException(
                    code=e.code,
                    message=e.message,
                    pastoral_message=e.pastoral_message,
                    status_code=response_status,
                )
