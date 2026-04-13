"""
Celery tasks para envio de notificações.
"""

import logging

import sentry_sdk
from celery import shared_task
from celery.exceptions import MaxRetriesExceededError
from django.conf import settings
from django.core.mail import send_mail

from clama.notifications.services.email_sender import enviar_email_oracao
from clama.notifications.services.zapi_sender import ZapiSender
from clama.notifications.utils import format_telefone_e164
from clama.orders.models import CanalEntrega, Pedido, PedidoStatus

logger = logging.getLogger("clama.notifications.tasks")


# Template de mensagem WhatsApp pastoral
WHATSAPP_MESSAGE_TEMPLATE = """🙏 *{nome}*, sua oração está aqui.

{oracao}

---
_Enviado com carinho pelo Clama_
_clama.me_"""


@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def enviar_oracao_task(self, pedido_id: str) -> None:
    """
    Envia a oração gerada por email ou WhatsApp.

    Roteamento automático baseado em pedido.canal_entrega.

    Args:
        pedido_id: UUID do pedido (string)
    """
    pedido = Pedido.objects.get(id=pedido_id)

    # Idempotência: já enviado
    if pedido.status == PedidoStatus.ENVIADA:
        logger.info(
            "enviar_oracao_ja_enviada",
            extra={
                "event": "enviar_oracao_skipped",
                "pedido_id": pedido_id,
            },
        )
        return

    # Validação: oração deve existir
    if not pedido.oracao_gerada:
        logger.error(
            "enviar_oracao_sem_oracao",
            extra={
                "event": "enviar_oracao_no_prayer",
                "pedido_id": pedido_id,
            },
        )
        pedido.status = PedidoStatus.ERRO
        pedido.save(update_fields=["status", "updated_at"])
        return

    try:
        # Roteamento por canal
        if pedido.canal_entrega == CanalEntrega.EMAIL:
            _enviar_por_email(pedido)
        elif pedido.canal_entrega == CanalEntrega.WHATSAPP:
            _enviar_por_whatsapp(pedido)
        else:
            logger.warning(
                "enviar_oracao_canal_desconhecido",
                extra={
                    "event": "enviar_oracao_unknown_channel",
                    "pedido_id": pedido_id,
                    "canal": pedido.canal_entrega,
                },
            )
            # Fallback para email
            _enviar_por_email(pedido)

        pedido.status = PedidoStatus.ENVIADA
        pedido.save(update_fields=["status", "updated_at"])

        logger.info(
            "enviar_oracao_concluido",
            extra={
                "event": "enviar_oracao_completed",
                "pedido_id": pedido_id,
                "canal": pedido.canal_entrega,
            },
        )

    except Exception as exc:
        logger.warning(
            "enviar_oracao_erro",
            extra={
                "event": "enviar_oracao_error",
                "pedido_id": pedido_id,
                "canal": pedido.canal_entrega,
                "attempt": self.request.retries + 1,
                "error": str(exc),
            },
        )
        try:
            # Backoff exponencial: 30s, 60s, 120s
            countdown = 30 * (2 ** self.request.retries)
            raise self.retry(exc=exc, countdown=countdown)
        except MaxRetriesExceededError:
            pedido.status = PedidoStatus.ERRO
            pedido.save(update_fields=["status", "updated_at"])
            logger.error(
                "enviar_oracao_erro_persistente",
                extra={
                    "event": "enviar_oracao_failed",
                    "pedido_id": pedido_id,
                    "canal": pedido.canal_entrega,
                },
            )
            sentry_sdk.capture_exception(exc)


def _enviar_por_email(pedido: Pedido) -> None:
    """Envia oração por email."""
    enviar_email_oracao(pedido)
    logger.info(
        "enviar_oracao_email_enviado",
        extra={
            "event": "email_sent",
            "pedido_id": str(pedido.id),
        },
    )


def _enviar_por_whatsapp(pedido: Pedido) -> None:
    """Envia oração por WhatsApp."""
    if not pedido.telefone:
        raise ValueError("Pedido sem telefone para envio por WhatsApp")

    # Formata telefone para E.164
    telefone_e164 = format_telefone_e164(pedido.telefone)

    # Monta mensagem
    mensagem = WHATSAPP_MESSAGE_TEMPLATE.format(
        nome=pedido.nome,
        oracao=pedido.oracao_gerada,
    )

    # Envia via Z-API
    sender = ZapiSender()
    result = sender.send(telefone_e164, mensagem)

    # Persiste message_id para tracking
    pedido.whatsapp_message_id = result.get("provider_message_id", "")
    pedido.save(update_fields=["whatsapp_message_id", "updated_at"])

    logger.info(
        "enviar_oracao_whatsapp_enviado",
        extra={
            "event": "whatsapp_sent",
            "pedido_id": str(pedido.id),
            "message_id": result.get("provider_message_id", ""),
        },
    )


@shared_task
def enviar_alerta_admin_task(pedido_id: str) -> None:
    """
    Envia alerta para admin quando pedido entra em ERRO.

    Envia email para ADMIN_ALERT_EMAIL e registra no Sentry.

    Args:
        pedido_id: UUID do pedido (string)
    """
    try:
        pedido = Pedido.objects.get(id=pedido_id)
    except Pedido.DoesNotExist:
        logger.warning(
            "alerta_admin_pedido_nao_encontrado",
            extra={
                "event": "admin_alert_pedido_not_found",
                "pedido_id": pedido_id,
            },
        )
        return

    # Verifica se ainda está em ERRO
    if pedido.status != PedidoStatus.ERRO:
        logger.info(
            "alerta_admin_status_mudou",
            extra={
                "event": "admin_alert_status_changed",
                "pedido_id": pedido_id,
                "current_status": pedido.status,
            },
        )
        return

    admin_email = getattr(settings, "ADMIN_ALERT_EMAIL", "pedro@clama.me")

    # Monta email
    subject = f"[Clama] Pedido em ERRO - {str(pedido.id)[:8]}"
    message = f"""Um pedido entrou em status ERRO e requer atenção.

ID do Pedido: {pedido.id}
Nome: {pedido.nome}
Email: {pedido.email}
Telefone: {pedido.telefone or 'Não informado'}
Plano: {pedido.plano.nome}
Valor: {pedido.valor_reais_str}
Canal de Entrega: {pedido.canal_entrega}
Número de Retentativas: {pedido.retry_count}

Último Erro:
{pedido.last_error or 'Não registrado'}

---
Acesse o admin para mais detalhes: {settings.FRONTEND_URL}/admin/pedidos/{pedido.id}
"""

    try:
        send_mail(
            subject=subject,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[admin_email],
            fail_silently=False,
        )

        logger.info(
            "alerta_admin_enviado",
            extra={
                "event": "admin_alert_sent",
                "pedido_id": pedido_id,
                "admin_email": admin_email,
            },
        )
    except Exception as exc:
        logger.error(
            "alerta_admin_erro_email",
            extra={
                "event": "admin_alert_email_failed",
                "pedido_id": pedido_id,
                "error": str(exc),
            },
        )
        sentry_sdk.capture_exception(exc)

    # Registra no Sentry também
    sentry_sdk.capture_message(
        f"Pedido em ERRO: {pedido.id}",
        level="error",
    )
