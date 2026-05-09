"""
Celery tasks específicas do app freemium.

P-V9 wave 2: `reconciliar_pedidos_freemium_orfaos` — varredura
periódica que detecta Pedidos `eh_gratuito=True` presos em
`AGUARDANDO_CONFIRMACAO_EMAIL` por mais de 48h. Cenário gerador:
`enviar_email_confirmacao_freemium_task` falhou permanentemente
(MaxRetriesExceeded), token expirou em 24h, mas o Pedido ficou stuck.

A task marca como ERRO + last_error="email_confirmacao_nao_entregue"
+ Sentry capture, e deleta os tokens associados (já estão expirados, mas
o cleanup mantém a tabela enxuta).

Agendamento: registrar via `django-celery-beat` (PeriodicTask) ou no
`CELERY_BEAT_SCHEDULE` do settings, rodando a cada 6h ou 24h. Na settings
default já adicionamos a entrada (ver `config/settings/base.py`
`CELERY_BEAT_SCHEDULE` — adicionado no patch P-V9).
"""

from __future__ import annotations

import logging
from datetime import timedelta

import sentry_sdk
from celery import shared_task
from django.utils import timezone

from clama.freemium.models import FreemiumConfirmationToken
from clama.orders.models import Pedido, PedidoStatus

logger = logging.getLogger("clama.freemium.tasks")

# Janela de tolerância para considerar um Pedido órfão. 48h cobre worst-
# case onde o e-mail de confirmação demorou (Resend backlog) + tentativas
# de re-envio + Celery retry; cap acima do TTL de 24h do token (frozen).
ORFAO_THRESHOLD_HOURS = 48


@shared_task
def reconciliar_pedidos_freemium_orfaos() -> dict:
    """
    Varre Pedidos freemium em `AGUARDANDO_CONFIRMACAO_EMAIL` por mais de
    48h e os move pra ERRO + dispara Sentry. Idempotente.

    Returns:
        Dict com `n_reconciliados` e `n_tokens_deletados` para inspeção
        em Flower / logs.
    """
    cutoff = timezone.now() - timedelta(hours=ORFAO_THRESHOLD_HOURS)
    qs = Pedido.objects.filter(
        eh_gratuito=True,
        status=PedidoStatus.AGUARDANDO_CONFIRMACAO_EMAIL,
        created_at__lt=cutoff,
    )

    pedido_ids: list = list(qs.values_list("id", flat=True))
    if not pedido_ids:
        logger.info(
            "reconciliar_pedidos_freemium_orfaos sem candidatos",
            extra={"event": "freemium_reconcile_noop"},
        )
        return {"n_reconciliados": 0, "n_tokens_deletados": 0}

    n_atualizados = qs.update(
        status=PedidoStatus.ERRO,
        last_error="email_confirmacao_nao_entregue",
        updated_at=timezone.now(),
    )
    n_tokens = (
        FreemiumConfirmationToken.objects.filter(pedido_id__in=pedido_ids)
        .delete()[0]
    )

    logger.warning(
        "Pedidos freemium órfãos reconciliados",
        extra={
            "event": "freemium_pedidos_orfaos_reconciliados",
            "n_reconciliados": n_atualizados,
            "n_tokens_deletados": n_tokens,
            "threshold_hours": ORFAO_THRESHOLD_HOURS,
        },
    )
    sentry_sdk.capture_message(
        f"Freemium: {n_atualizados} pedidos órfãos reconciliados (>48h "
        f"em AGUARDANDO_CONFIRMACAO_EMAIL).",
        level="warning",
    )

    return {
        "n_reconciliados": n_atualizados,
        "n_tokens_deletados": n_tokens,
    }
