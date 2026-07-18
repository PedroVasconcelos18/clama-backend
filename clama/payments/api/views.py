"""
Views da API de pagamentos.
"""

import logging

import sentry_sdk
from django.conf import settings
from django.db import transaction
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from clama.core.exceptions import PastoralAPIException
from clama.core.money import centavos_to_reais_str
from clama.orders.models import Pedido, PedidoStatus
from clama.payments.exceptions import PaymentProviderError
from clama.payments.services.base import PaymentProvider
from clama.payments.services.mercadopago_client import MercadoPagoClient

logger = logging.getLogger("clama.payments.api")


# Pastoral genérica para erros operacionais/configuração do gateway que o
# usuário final não consegue resolver (credencial errada, conta mal configurada).
# Esconde o detalhe técnico.
MSG_PAYMENT_CONFIG_ERROR = (
    "Tivemos um soluço processando seu pagamento. Já estamos olhando — "
    "tenta de novo em alguns instantes ou escreve pra contato@clama.me."
)

# Trechos que indicam erro de configuração/credencial (nada que o usuário possa
# corrigir). Comparação case-insensitive contra a mensagem do Mercado Pago.
# Mantido específico a credencial/autorização para não classificar como admin-side
# um 4xx que o usuário poderia resolver.
_MP_ADMIN_SIDE_KEYWORDS = (
    "credential",
    "credencial",
    "unauthorized",
    "não autorizado",
    "nao autorizado",
    "forbidden",
    "access token",
    "access_token",
    "invalid_token",
    "invalid access",
    "collector",
)


def _is_admin_side_mp_error(description: str) -> bool:
    """True se a mensagem do Mercado Pago aponta erro que só o admin resolve."""
    if not description:
        return False
    lowered = description.lower()
    return any(keyword in lowered for keyword in _MP_ADMIN_SIDE_KEYWORDS)


def _extract_mp_error_description(upstream_body) -> str:
    """Extrai a `cause[].description` (senão `message`) do corpo de erro do MP — só p/ classificação/log."""
    if not isinstance(upstream_body, dict):
        return ""
    cause = upstream_body.get("cause")
    if isinstance(cause, list) and cause:
        first = cause[0]
        if isinstance(first, dict) and isinstance(first.get("description"), str):
            return first["description"].strip()
    message = upstream_body.get("message")
    if isinstance(message, str):
        return message.strip()
    return ""


def _pastoral_message_from_mp_error(upstream_body, fallback: str) -> tuple[str, bool]:
    """
    Classifica o erro 4xx do Mercado Pago e devolve uma mensagem pastoral pt-BR.

    O MP retorna mensagens técnicas **em inglês** — NUNCA repassamos o texto cru à
    Juliana. Se a mensagem indica problema de config/credencial (admin-side),
    devolve a pastoral genérica de configuração + sinaliza alerta ao admin; caso
    contrário devolve o `fallback` (o `pastoral_message` pt-BR da própria exceção).

    Retorna `(pastoral_message, is_admin_side)`.
    """
    description = _extract_mp_error_description(upstream_body)
    if description and _is_admin_side_mp_error(description):
        return MSG_PAYMENT_CONFIG_ERROR, True
    return fallback, False


class CheckoutResponseSerializer(serializers.Serializer):
    """Serializer para resposta do checkout."""

    checkout_url = serializers.URLField()
    pedido_id = serializers.UUIDField()


class CheckoutView(APIView):
    """
    Cria cobrança no gateway (Mercado Pago) e retorna URL de checkout.

    Idempotente em nível de pedido — múltiplas chamadas em pedido
    AGUARDANDO_PAGAMENTO reutilizam a cobrança já criada.
    """

    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "pedidos_checkout"

    def __init__(self, provider: PaymentProvider | None = None, **kwargs):
        """
        Inicializa a view com o port de pagamento injetável para testes.

        Args:
            provider: Implementação de PaymentProvider (opcional, para testes)
        """
        super().__init__(**kwargs)
        self._provider = provider

    @property
    def provider(self) -> PaymentProvider:
        """Retorna o provider de pagamento, criando o default se necessário."""
        if self._provider is None:
            self._provider = MercadoPagoClient()
        return self._provider

    def _get_pedido_locked(self, pedido_id: str) -> Pedido:
        """
        Busca pedido por ID com lock pessimista (SELECT FOR UPDATE).

        Deve ser chamado dentro de uma transação. Serializa requests concorrentes
        no MESMO pedido (double-click, retries do front), prevenindo cobranças duplicadas.

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
            ) from None

    def _validate_status_for_checkout(self, pedido: Pedido) -> None:
        """
        Valida se o pedido pode fazer checkout.

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
        Valida dados do pedido exigidos para gerar a cobrança.

        Falha rápido com 422 em vez de delegar ao gateway.

        Raises:
            PastoralAPIException: Se dados obrigatórios estiverem ausentes (422)
                ou se o valor for menor que o mínimo aceito (422).
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

        min_centavos = getattr(settings, "MERCADOPAGO_MIN_VALOR_CENTAVOS", 1)
        if pedido.valor_centavos < min_centavos:
            min_str = centavos_to_reais_str(min_centavos)
            raise PastoralAPIException(
                code="valor_abaixo_do_minimo",
                message=(
                    f"Valor da cobrança ({centavos_to_reais_str(pedido.valor_centavos)}) "
                    f"é menor que o mínimo aceito ({min_str})"
                ),
                pastoral_message=(
                    f"O valor mínimo aceito pelo processador de pagamentos é {min_str}. "
                    "Escolha um valor igual ou maior pra continuar."
                ),
                status_code=422,
            )

    @extend_schema(
        tags=["Pedidos"],
        summary="Criar checkout de pagamento",
        description="""
Cria uma cobrança no Mercado Pago (Checkout Pro / PIX) e retorna a URL de checkout.

**Idempotência:** Múltiplas chamadas em pedido AGUARDANDO_PAGAMENTO reutilizam a
cobrança já criada.

**Status permitido:** Apenas AGUARDANDO_PAGAMENTO. Pedidos já pagos retornam 409.

**Tipo de pagamento:** PIX (via `excluded_payment_types` na preference).
        """,
        responses={
            200: OpenApiResponse(
                response=CheckoutResponseSerializer,
                description="URL de checkout criada com sucesso",
            ),
            404: OpenApiResponse(description="Pedido não encontrado"),
            409: OpenApiResponse(description="Pedido já foi pago"),
            422: OpenApiResponse(description="Dados do pedido inválidos ou rejeitados pelo gateway"),
            503: OpenApiResponse(description="Gateway indisponível após retries"),
        },
    )
    def post(self, request, id):
        """
        Cria cobrança no Mercado Pago e retorna URL de checkout.

        Idempotente: requests concorrentes ou repetidas no mesmo pedido reutilizam
        a cobrança existente em vez de criar duplicadas.

        Args:
            request: Request HTTP
            id: UUID do pedido

        Returns:
            Response com checkout_url e pedido_id
        """
        # A transação serializa requests concorrentes no mesmo pedido via
        # SELECT FOR UPDATE. O lock é mantido durante a chamada ao gateway.
        with transaction.atomic():
            pedido = self._get_pedido_locked(id)
            self._validate_status_for_checkout(pedido)
            self._validate_pedido_data(pedido)

            # Idempotência: cobrança já criada → reutiliza.
            if pedido.provider_payment_id and pedido.provider_checkout_url:
                logger.info(
                    "Checkout reused",
                    extra={
                        "event": "checkout_reused",
                        "pedido_id": str(pedido.id),
                        "provider_payment_id": pedido.provider_payment_id,
                    },
                )
                return Response(
                    {
                        "checkout_url": pedido.provider_checkout_url,
                        "pedido_id": str(pedido.id),
                    },
                    status=status.HTTP_200_OK,
                )

            try:
                # Descrição curta sem PII
                descricao = f"Pedido Clama #{str(pedido.id)[:8]}"

                cobranca = self.provider.criar_cobranca(
                    nome=pedido.nome,
                    email=pedido.email,
                    cpf_cnpj=pedido.cpf_cnpj,
                    valor_centavos=pedido.valor_centavos,
                    descricao=descricao,
                    pedido_id=str(pedido.id),
                )

                pedido.provider_payment_id = cobranca.provider_payment_id
                pedido.provider_checkout_url = cobranca.checkout_url
                pedido.save(
                    update_fields=[
                        "provider_payment_id",
                        "provider_checkout_url",
                        "updated_at",
                    ]
                )

                logger.info(
                    "Checkout created",
                    extra={
                        "event": "checkout_created",
                        "pedido_id": str(pedido.id),
                        "provider_payment_id": cobranca.provider_payment_id,
                    },
                )

                return Response(
                    {
                        "checkout_url": cobranca.checkout_url,
                        "pedido_id": str(pedido.id),
                    },
                    status=status.HTTP_200_OK,
                )

            except PaymentProviderError as e:
                # 4xx do gateway = dados/config rejeitados (422). Rede/timeout/5xx = upstream fora (503).
                # Usar 502 aqui quebra CORS: a Cloudflare substitui o body pela própria página de erro.
                is_admin_side = False
                if e.upstream_status is not None and 400 <= e.upstream_status < 500:
                    response_status = 422
                    pastoral, is_admin_side = _pastoral_message_from_mp_error(
                        e.upstream_body, e.pastoral_message
                    )
                else:
                    response_status = 503
                    pastoral = e.pastoral_message

                logger.error(
                    "Checkout failed",
                    extra={
                        "event": "checkout_failed",
                        "pedido_id": str(pedido.id),
                        "error": str(e),
                        "upstream_status": e.upstream_status,
                        "upstream_body": e.upstream_body,
                        "admin_side": is_admin_side,
                    },
                )
                # Erros de configuração/credencial do gateway são silenciosos para
                # o usuário mas precisam alertar o admin.
                if is_admin_side:
                    # Sem interpolar upstream_body (pode conter PII); detalhe fica no log estruturado.
                    sentry_sdk.capture_message(
                        "Mercado Pago admin-side error no checkout (ver logs)",
                        level="error",
                    )
                raise PastoralAPIException(
                    code=e.code,
                    message=e.message,
                    pastoral_message=pastoral,
                    status_code=response_status,
                ) from e
