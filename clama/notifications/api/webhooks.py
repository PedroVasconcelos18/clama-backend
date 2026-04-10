"""
Webhook endpoint para eventos do Z-API (WhatsApp).

Recebe callbacks de status de entrega das mensagens WhatsApp.
"""

import logging

import sentry_sdk
from django.db import transaction
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from clama.orders.models import Pedido, PedidoStatus
from clama.payments.models import WebhookEvento, WebhookEventoStatus, WebhookProvider

logger = logging.getLogger("clama.notifications.webhook")

# Status de mensagem do Z-API
ZAPI_STATUS_SENT = "SENT"
ZAPI_STATUS_DELIVERED = "DELIVERED"
ZAPI_STATUS_READ = "READ"
ZAPI_STATUS_FAILED = "FAILED"


@method_decorator(csrf_exempt, name="dispatch")
class ZapiWebhookView(APIView):
    """
    Recebe webhooks de status de mensagem do Z-API.

    Quando uma mensagem é entregue ou lida, atualiza os timestamps no pedido.
    Quando uma mensagem falha, dispara fallback para envio por email.

    **Idempotência:** Cada evento é registrado na tabela WebhookEvento.
    Eventos duplicados são ignorados automaticamente.

    **Nota:** Z-API não suporta HMAC. Considerar IP allowlist via infra.
    """

    permission_classes = [AllowAny]
    throttle_classes = []  # Desabilita throttle para webhooks

    @extend_schema(
        tags=["Webhooks"],
        summary="Webhook Z-API",
        description="""
Recebe eventos de status de mensagem do Z-API (WhatsApp).

**Status aceitos:**
- SENT: Mensagem enviada
- DELIVERED: Mensagem entregue no dispositivo
- READ: Mensagem lida pelo destinatário
- FAILED: Falha no envio

**Comportamento:**
- DELIVERED/READ: atualiza timestamps no pedido
- FAILED: dispara fallback para envio por email
- Evento duplicado: retorna 200 com {"status": "already_processed"}

**Idempotência:** Garantida por registro único de messageId.
        """,
        request=None,
        responses={
            200: {"type": "object", "properties": {"status": {"type": "string"}}},
            400: {"description": "Payload inválido"},
            500: {"description": "Erro interno"},
        },
    )
    def post(self, request):
        """
        Processa webhook do Z-API com idempotência completa.

        Args:
            request: Request com payload JSON do Z-API

        Returns:
            Response com status do processamento
        """
        payload = request.data

        # Extrai ID da mensagem e status
        # Z-API envia messageId no nível do evento
        message_id = payload.get("messageId") or payload.get("id", "")
        message_status = payload.get("status", "").upper()

        if not message_id:
            logger.warning(
                "Z-API webhook: missing messageId",
                extra={"event": "zapi_webhook_invalid", "reason": "missing_message_id"},
            )
            return Response(
                {"error": {"code": "invalid_payload", "message": "Missing messageId"}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Registra evento (idempotência)
        webhook_evento, created = WebhookEvento.objects.try_register(
            provider=WebhookProvider.ZAPI,
            external_event_id=f"{message_id}:{message_status}",
            event_type=f"MESSAGE_{message_status}",
            payload=payload,
        )

        if not created:
            # Evento já processado - retorna sucesso sem efeitos colaterais
            logger.info(
                "Z-API webhook: already processed",
                extra={
                    "event": "zapi_webhook_duplicate",
                    "message_id": message_id,
                    "status": message_status,
                },
            )
            return Response({"status": "already_processed"}, status=status.HTTP_200_OK)

        # Processa novo evento
        try:
            with transaction.atomic():
                # Busca pedido pelo whatsapp_message_id
                try:
                    pedido = Pedido.objects.select_for_update().get(
                        whatsapp_message_id=message_id
                    )
                except Pedido.DoesNotExist:
                    webhook_evento.mark_ignored(f"Pedido não encontrado: {message_id}")
                    logger.warning(
                        "Z-API webhook: pedido not found",
                        extra={
                            "event": "zapi_webhook_orphan",
                            "message_id": message_id,
                        },
                    )
                    return Response({"status": "orphan"}, status=status.HTTP_200_OK)

                # Processa conforme status
                if message_status == ZAPI_STATUS_DELIVERED:
                    pedido.whatsapp_delivered_at = timezone.now()
                    pedido.save(update_fields=["whatsapp_delivered_at", "updated_at"])
                    webhook_evento.mark_processed(pedido=pedido)

                    logger.info(
                        "Z-API webhook: message delivered",
                        extra={
                            "event": "zapi_webhook_delivered",
                            "pedido_id": str(pedido.id),
                            "message_id": message_id,
                        },
                    )

                elif message_status == ZAPI_STATUS_READ:
                    pedido.whatsapp_read_at = timezone.now()
                    pedido.save(update_fields=["whatsapp_read_at", "updated_at"])
                    webhook_evento.mark_processed(pedido=pedido)

                    logger.info(
                        "Z-API webhook: message read",
                        extra={
                            "event": "zapi_webhook_read",
                            "pedido_id": str(pedido.id),
                            "message_id": message_id,
                        },
                    )

                elif message_status == ZAPI_STATUS_FAILED:
                    # Falha no envio - dispara fallback para email
                    pedido.status = PedidoStatus.ERRO
                    pedido.last_error = f"WhatsApp delivery failed: {payload.get('error', 'Unknown error')}"
                    pedido.save(update_fields=["status", "last_error", "updated_at"])
                    webhook_evento.mark_processed(pedido=pedido)

                    # Dispara fallback para email após commit
                    from clama.notifications.tasks import enviar_oracao_task

                    pedido_id = str(pedido.id)

                    def dispatch_email_fallback():
                        # Muda canal para email e re-envia
                        p = Pedido.objects.get(id=pedido_id)
                        p.canal_entrega = "email"
                        p.status = PedidoStatus.ORACAO_GERADA
                        p.save(update_fields=["canal_entrega", "status", "updated_at"])
                        enviar_oracao_task.delay(pedido_id)

                    transaction.on_commit(dispatch_email_fallback)

                    logger.warning(
                        "Z-API webhook: message failed, fallback to email",
                        extra={
                            "event": "zapi_webhook_failed",
                            "pedido_id": str(pedido.id),
                            "message_id": message_id,
                        },
                    )
                    sentry_sdk.capture_message(
                        f"WhatsApp delivery failed for pedido {pedido.id}",
                        level="warning",
                    )

                else:
                    # Status não processado (SENT, etc)
                    webhook_evento.mark_ignored(f"Status não processado: {message_status}")
                    logger.info(
                        "Z-API webhook: ignored status",
                        extra={
                            "event": "zapi_webhook_ignored",
                            "status": message_status,
                            "message_id": message_id,
                        },
                    )

            return Response({"status": "ok"}, status=status.HTTP_200_OK)

        except Exception as exc:
            # Erro inesperado
            webhook_evento.mark_error(str(exc)[:2000])
            sentry_sdk.capture_exception(exc)

            logger.exception(
                "Z-API webhook error",
                extra={
                    "event": "zapi_webhook_error",
                    "message_id": message_id,
                    "error": str(exc),
                },
            )

            return Response(
                {"error": {"code": "internal_error", "message": "Processing failed"}},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
