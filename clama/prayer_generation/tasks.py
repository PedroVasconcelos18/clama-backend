"""
Celery tasks para geração de orações.

Implementa fallback de reenvio: quando a geração falha após retries do Celery,
agenda uma nova tentativa em 5 minutos (até 3 vezes) ao invés de marcar ERRO
imediatamente. Isso permite recuperação de falhas transitórias da API.
"""

import logging

import anthropic
import sentry_sdk
from celery import MaxRetriesExceededError, shared_task

from clama.orders.models import Pedido, PedidoStatus
from clama.prayer_generation.exceptions import PrayerGenerationError
from clama.prayer_generation.services.anthropic_client import AnthropicClient

logger = logging.getLogger("clama.prayer_generation.tasks")

# Número máximo de reagendamentos (além dos retries do Celery)
MAX_RESCHEDULE_COUNT = 3
# Intervalo entre reagendamentos em segundos (5 minutos)
RESCHEDULE_DELAY_SECONDS = 300


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def gerar_oracao_task(self, pedido_id: str) -> None:
    """
    Gera oração personalizada para o pedido via Claude API.

    Implementa resiliência em dois níveis:
    1. Retries do Celery (3x com backoff) para falhas rápidas
    2. Reagendamento (3x a cada 5min) para falhas persistentes

    Args:
        pedido_id: UUID do pedido (string)
    """
    pedido = Pedido.objects.get(id=pedido_id)

    # Idempotência: já processado
    if pedido.status in (PedidoStatus.ORACAO_GERADA, PedidoStatus.ENVIADA):
        logger.info(
            "gerar_oracao_ja_processado",
            extra={
                "event": "gerar_oracao_skipped",
                "pedido_id": pedido_id,
                "current_status": pedido.status,
            },
        )
        return

    try:
        # Atualiza status para GERANDO_ORACAO
        pedido.status = PedidoStatus.GERANDO_ORACAO
        pedido.save(update_fields=["status", "updated_at"])

        logger.info(
            "gerar_oracao_iniciando",
            extra={
                "event": "gerar_oracao_started",
                "pedido_id": pedido_id,
                "retry_count": pedido.retry_count,
            },
        )

        # Gera oração via AnthropicClient
        oracao = AnthropicClient().gerar_oracao(pedido)

        # Salva oração e atualiza status
        pedido.oracao_gerada = oracao
        pedido.status = PedidoStatus.ORACAO_GERADA
        pedido.save(update_fields=["oracao_gerada", "status", "updated_at"])

        logger.info(
            "gerar_oracao_concluido",
            extra={
                "event": "gerar_oracao_completed",
                "pedido_id": pedido_id,
            },
        )

        # Encadeia task de envio (import lazy para evitar circular import)
        from clama.notifications.tasks import enviar_oracao_task

        enviar_oracao_task.delay(pedido_id)

    except (PrayerGenerationError, anthropic.APITimeoutError, anthropic.APIConnectionError) as exc:
        logger.warning(
            "gerar_oracao_erro",
            extra={
                "event": "gerar_oracao_error",
                "pedido_id": pedido_id,
                "attempt": self.request.retries + 1,
                "error": str(exc),
            },
        )
        try:
            raise self.retry(exc=exc)
        except MaxRetriesExceededError:
            _handle_persistent_failure(pedido, exc)


def _handle_persistent_failure(pedido: Pedido, exc: Exception) -> None:
    """
    Lida com falhas persistentes após retries do Celery.

    Implementa fallback de reagendamento: agenda nova tentativa em 5 minutos
    até o limite de 3 reagendamentos. Após isso, marca pedido como ERRO.

    Args:
        pedido: Pedido que falhou
        exc: Exceção que causou a falha
    """
    pedido_id = str(pedido.id)

    # Salva o erro no campo last_error
    pedido.last_error = str(exc)[:2000]  # Trunca para não exceder limite

    # Verifica se ainda pode reagendar
    if pedido.retry_count < MAX_RESCHEDULE_COUNT:
        # Incrementa contador e agenda reenvio
        pedido.retry_count += 1
        pedido.status = PedidoStatus.AGUARDANDO_REENVIO
        pedido.save(update_fields=["status", "retry_count", "last_error", "updated_at"])

        logger.info(
            "gerar_oracao_reagendado",
            extra={
                "event": "gerar_oracao_rescheduled",
                "pedido_id": pedido_id,
                "retry_count": pedido.retry_count,
                "delay_seconds": RESCHEDULE_DELAY_SECONDS,
            },
        )

        # Agenda nova tentativa em 5 minutos
        gerar_oracao_task.apply_async(
            args=[pedido_id],
            countdown=RESCHEDULE_DELAY_SECONDS,
        )
    else:
        # Esgotou reagendamentos - marca como erro definitivo
        pedido.status = PedidoStatus.ERRO
        pedido.save(update_fields=["status", "last_error", "updated_at"])

        logger.error(
            "gerar_oracao_erro_definitivo",
            extra={
                "event": "gerar_oracao_failed_permanently",
                "pedido_id": pedido_id,
                "retry_count": pedido.retry_count,
            },
        )

        # Captura no Sentry para visibilidade
        sentry_sdk.capture_exception(exc)
