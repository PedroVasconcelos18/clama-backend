"""
Webhook endpoint para eventos do Asaas.

Versão completa com:
- Idempotência via WebhookEvento (Story 3.1)
- Validação HMAC via middleware (Story 3.2)
- Processamento transacional (Story 3.3)
"""

import logging

import sentry_sdk
from django.db import transaction
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from clama.orders.models import Pedido
from clama.payments.models import WebhookEvento, WebhookEventoStatus, WebhookProvider

logger = logging.getLogger("clama.payments.webhook")

# Eventos do Asaas que indicam pagamento confirmado
ACCEPTED_EVENTS = {"PAYMENT_CONFIRMED", "PAYMENT_RECEIVED"}


@method_decorator(csrf_exempt, name="dispatch")
class AsaasWebhookView(APIView):
    """
    Recebe webhooks de pagamento do Asaas.

    Quando um pagamento é confirmado, atualiza o pedido para PAGO
    e dispara a geração da oração via Celery.

    **Idempotência:** Cada evento é registrado na tabela WebhookEvento.
    Eventos duplicados são ignorados automaticamente.

    **Segurança:** Em produção, middleware AsaasWebhookAuthMiddleware
    valida o token do Asaas antes de chegar aqui.
    """

    permission_classes = [AllowAny]
    throttle_classes = []  # Desabilita throttle para webhooks

    @extend_schema(
        tags=["Webhooks"],
        summary="Webhook Asaas",
        description="""
Recebe eventos de pagamento do Asaas.

**Eventos aceitos:** PAYMENT_CONFIRMED, PAYMENT_RECEIVED

**Comportamento:**
- Pagamento confirmado: atualiza pedido para PAGO e dispara geração de oração
- Evento desconhecido: retorna 200 (marca como IGNORADO)
- Pedido não encontrado: retorna 200 (marca como IGNORADO)
- Evento duplicado: retorna 200 com {"status": "already_processed"}

**Idempotência:** Garantida por registro único de external_event_id.
        """,
        request=None,
        responses={
            200: {"type": "object", "properties": {"status": {"type": "string"}}},
            400: {"description": "Payload inválido"},
            500: {"description": "Erro interno (Asaas retentará)"},
        },
    )
    def post(self, request):
        """
        Processa webhook do Asaas com idempotência completa.

        Args:
            request: Request com payload JSON do Asaas

        Returns:
            Response com status do processamento
        """
        payload = request.data

        # Extrai ID único do evento (diferente do payment.id)
        external_event_id = payload.get("id")
        event_type = payload.get("event", "")

        if not external_event_id:
            logger.warning(
                "Asaas webhook: missing event id",
                extra={"event": "asaas_webhook_invalid", "reason": "missing_event_id"},
            )
            return Response(
                {"error": {"code": "invalid_payload", "message": "Missing event id"}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Registra evento (idempotência)
        webhook_evento, created = WebhookEvento.objects.try_register(
            provider=WebhookProvider.ASAAS,
            external_event_id=external_event_id,
            event_type=event_type,
            payload=payload,
        )

        if not created:
            # Evento já processado - retorna sucesso sem efeitos colaterais
            logger.info(
                "Asaas webhook: already processed",
                extra={
                    "event": "asaas_webhook_duplicate",
                    "external_event_id": external_event_id,
                },
            )
            return Response({"status": "already_processed"}, status=status.HTTP_200_OK)

        # Processa novo evento
        try:
            with transaction.atomic():
                # Verifica se é evento aceito
                if event_type not in ACCEPTED_EVENTS:
                    webhook_evento.mark_ignored(f"Evento não suportado: {event_type}")
                    logger.info(
                        "Asaas webhook: ignored event type",
                        extra={
                            "event": "asaas_webhook_ignored",
                            "event_type": event_type,
                            "external_event_id": external_event_id,
                        },
                    )
                    return Response({"status": "ignored"}, status=status.HTTP_200_OK)

                # Busca pedido pelo charge_id com lock
                payment_data = payload.get("payment", {})
                payment_id = payment_data.get("id", "")

                try:
                    pedido = Pedido.objects.select_for_update().get(
                        asaas_charge_id=payment_id
                    )
                except Pedido.DoesNotExist:
                    webhook_evento.mark_ignored(f"Pedido não encontrado: {payment_id}")
                    logger.warning(
                        "Asaas webhook: pedido not found",
                        extra={
                            "event": "asaas_webhook_orphan",
                            "payment_id": payment_id,
                            "external_event_id": external_event_id,
                        },
                    )
                    return Response({"status": "orphan"}, status=status.HTTP_200_OK)

                # Marca como pago
                pedido.marcar_como_pago()

                # Atualiza webhook_evento
                webhook_evento.mark_processed(pedido=pedido)

                # Dispara task após commit da transação
                # Import local para evitar circular import
                from clama.prayer_generation.tasks import gerar_oracao_task

                pedido_id = str(pedido.id)
                transaction.on_commit(lambda: gerar_oracao_task.delay(pedido_id))

                logger.info(
                    "Asaas webhook: payment confirmed",
                    extra={
                        "event": "asaas_webhook_payment_confirmed",
                        "pedido_id": str(pedido.id),
                        "payment_id": payment_id,
                        "external_event_id": external_event_id,
                    },
                )

            return Response({"status": "ok"}, status=status.HTTP_200_OK)

        except Exception as exc:
            # Erro inesperado - registra e deixa Asaas retentar
            webhook_evento.mark_error(str(exc)[:2000])
            sentry_sdk.capture_exception(exc)

            logger.exception(
                "Asaas webhook error",
                extra={
                    "event": "asaas_webhook_error",
                    "external_event_id": external_event_id,
                    "error": str(exc),
                },
            )

            return Response(
                {"error": {"code": "internal_error", "message": "Processing failed"}},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
