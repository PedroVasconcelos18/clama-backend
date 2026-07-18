"""
Webhook endpoint para eventos do Mercado Pago.

Idempotência terminal (AD-2), validação de assinatura via middleware (AD-3),
fetch fora do lock + provisão approved-only (AD-4/AD-5).
"""

import logging

import sentry_sdk
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from clama.core.exceptions import PastoralAPIException
from clama.orders.models import Pedido
from clama.payments.exceptions import PaymentProviderError
from clama.payments.models import WebhookEvento, WebhookEventoStatus, WebhookProvider
from clama.payments.services.base import StatusPagamento
from clama.payments.services.mercadopago_client import MercadoPagoClient

logger = logging.getLogger("clama.payments.webhook")

# Estados terminais de WebhookEvento — só eles curto-circuitam como já processado (AD-2).
# RECEBIDO/ERRO são reprocessáveis (o Mercado Pago reenvia a mesma notificação após um 500).
_TERMINAL_WEBHOOK_STATES = {
    WebhookEventoStatus.PROCESSADO,
    WebhookEventoStatus.IGNORADO,
}


@method_decorator(csrf_exempt, name="dispatch")
class MercadoPagoWebhookView(APIView):
    """
    Recebe webhooks de pagamento do Mercado Pago (AD-2, AD-4, AD-5).

    Fluxo:
    - Idempotência por `id` da notificação; curto-circuita só se a linha existente
      está em estado terminal (PROCESSADO/IGNORADO). RECEBIDO/ERRO → reprocessa.
    - `type != "payment"` → ignora + 200, sem buscar o pagamento.
    - Busca o pagamento no MP (via port, FORA de qualquer lock) usando o `data.id`
      assinado do query param.
    - Só provisiona se o pagamento estiver `approved`, sob `select_for_update` + state
      guard `marcar_como_pago` (409 de estado = sucesso idempotente → 200, nunca 500).

    Segurança: `MercadoPagoWebhookAuthMiddleware` valida a assinatura HMAC antes daqui.
    """

    permission_classes = [AllowAny]
    throttle_classes = []  # Webhook não tem throttle (MP retria legitimamente)

    def __init__(self, provider=None, **kwargs):
        """Inicializa com o port de pagamento injetável para testes."""
        super().__init__(**kwargs)
        self._provider = provider

    @property
    def provider(self):
        """Retorna o provider, criando o default se necessário."""
        if self._provider is None:
            self._provider = MercadoPagoClient()
        return self._provider

    @extend_schema(
        tags=["Webhooks"],
        summary="Webhook Mercado Pago",
        request=None,
        responses={
            200: {"type": "object", "properties": {"status": {"type": "string"}}},
            400: {"description": "Payload inválido"},
            500: {"description": "Erro interno (Mercado Pago retentará)"},
        },
    )
    def post(self, request):
        """Processa a notificação do Mercado Pago com idempotência terminal e provisão approved-only."""
        payload = request.data if isinstance(request.data, dict) else {}
        external_event_id = payload.get("id")
        tipo = payload.get("type", "")

        if external_event_id is None:
            logger.warning(
                "Mercado Pago webhook: missing notification id",
                extra={"event": "mercadopago_webhook_invalid", "reason": "missing_id"},
            )
            return Response(
                {"error": {"code": "invalid_payload", "message": "Missing notification id"}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        external_event_id = str(external_event_id)

        # Idempotência (AD-2): registra a notificação; curto-circuita só se terminal.
        webhook_evento, created = WebhookEvento.objects.try_register(
            provider=WebhookProvider.MERCADO_PAGO,
            external_event_id=external_event_id,
            event_type=tipo,
            payload=payload,
        )
        if not created and webhook_evento.status in _TERMINAL_WEBHOOK_STATES:
            logger.info(
                "Mercado Pago webhook: already processed",
                extra={
                    "event": "mercadopago_webhook_duplicate",
                    "external_event_id": external_event_id,
                },
            )
            return Response({"status": "already_processed"}, status=status.HTTP_200_OK)

        # AD-4: só notificações de pagamento; demais → ignora sem fetch.
        if tipo != "payment":
            webhook_evento.mark_ignored(f"tipo não-payment: {tipo}")
            return Response({"status": "ignored"}, status=status.HTTP_200_OK)

        # `data.id` vem do query param (o valor assinado — AD-3/AD-4), nunca do body.
        data_id = request.GET.get("data.id", "")
        if not data_id:
            webhook_evento.mark_ignored("data.id ausente no query")
            return Response({"status": "ignored"}, status=status.HTTP_200_OK)

        # Busca o pagamento no MP FORA de qualquer lock de linha (AD-4).
        try:
            pagamento = self.provider.buscar_pagamento(data_id)
        except PaymentProviderError as exc:
            if exc.upstream_status is not None and 400 <= exc.upstream_status < 500:
                # 4xx NÃO é transiente (token errado, pagamento inexistente) — o MP
                # retentar não resolve. Marca ignorado + alerta admin e retorna 200,
                # evitando loop infinito de retry/500 (AD-5: não classificar não-retriável como 500).
                webhook_evento.mark_ignored(f"fetch 4xx do Mercado Pago: {exc.upstream_status}")
                sentry_sdk.capture_message(
                    "Mercado Pago webhook: fetch 4xx (config/credencial ou pagamento inexistente)",
                    level="error",
                )
                logger.warning(
                    "Mercado Pago webhook: payment fetch 4xx (non-retriable)",
                    extra={
                        "event": "mercadopago_webhook_fetch_4xx",
                        "external_event_id": external_event_id,
                        "upstream_status": exc.upstream_status,
                    },
                )
                return Response({"status": "ignored"}, status=status.HTTP_200_OK)
            # 5xx/rede: transiente → linha reprocessável (não-terminal) + 500 (MP retria).
            webhook_evento.mark_error(str(exc)[:2000])
            sentry_sdk.capture_exception(exc)
            logger.warning(
                "Mercado Pago webhook: payment fetch failed",
                extra={
                    "event": "mercadopago_webhook_fetch_failed",
                    "external_event_id": external_event_id,
                    "data_id": data_id,
                },
            )
            return Response(
                {"error": {"code": "fetch_failed", "message": "Payment fetch failed"}},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        # Só provisiona se aprovado (AD-4). Qualquer outro status → ignora + 200.
        if pagamento.status != StatusPagamento.APROVADO:
            webhook_evento.mark_ignored(f"pagamento não-aprovado: {pagamento.raw_status}")
            return Response({"status": "ignored"}, status=status.HTTP_200_OK)

        external_reference = pagamento.external_reference
        if not external_reference:
            webhook_evento.mark_ignored("pagamento sem external_reference")
            return Response({"status": "ignored"}, status=status.HTTP_200_OK)

        # Provisão sob lock (AD-5): state guard garante provisão única.
        try:
            with transaction.atomic():
                pedido = Pedido.objects.select_for_update().get(id=external_reference)
                # Re-lê o status via state guard; 409 se já não está AGUARDANDO_PAGAMENTO.
                pedido.marcar_como_pago()
                webhook_evento.mark_processed(pedido=pedido)

                pedido_id = str(pedido.id)
                # Import local para evitar circular import
                from clama.prayer_generation.tasks import gerar_oracao_task

                transaction.on_commit(lambda: gerar_oracao_task.delay(pedido_id))
        except (Pedido.DoesNotExist, ValidationError, ValueError):
            # ValidationError: external_reference não é um UUID válido (UUIDField levanta
            # django.core.exceptions.ValidationError, não ValueError, no lookup).
            webhook_evento.mark_ignored(f"pedido não encontrado: {external_reference}")
            return Response({"status": "ignored"}, status=status.HTTP_200_OK)
        except PastoralAPIException:
            # AD-5: 409 de estado (pedido já pago) = sucesso idempotente → 200, nunca 500.
            webhook_evento.mark_ignored("pedido já processado (idempotente)")
            return Response({"status": "already_paid"}, status=status.HTTP_200_OK)
        except Exception as exc:
            # Só exceção genuinamente inesperada → linha reprocessável + 500 (MP retria).
            webhook_evento.mark_error(str(exc)[:2000])
            sentry_sdk.capture_exception(exc)
            logger.exception(
                "Mercado Pago webhook error",
                extra={
                    "event": "mercadopago_webhook_error",
                    "external_event_id": external_event_id,
                    "error": str(exc),
                },
            )
            return Response(
                {"error": {"code": "internal_error", "message": "Processing failed"}},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        logger.info(
            "Mercado Pago webhook: payment confirmed",
            extra={
                "event": "mercadopago_webhook_payment_confirmed",
                "pedido_id": external_reference,
                "external_event_id": external_event_id,
            },
        )
        return Response({"status": "ok"}, status=status.HTTP_200_OK)
