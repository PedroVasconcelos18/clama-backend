"""
Signals para o app orders.

Dispara alertas quando pedidos entram em estado de erro.
"""

import logging

from django.core.cache import cache
from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from clama.orders.models import Pedido, PedidoStatus

logger = logging.getLogger("clama.orders.signals")

# TTL para evitar alertas duplicados (1 hora)
ALERT_THROTTLE_TTL = 3600


@receiver(post_save, sender=Pedido)
def on_pedido_status_change(sender, instance: Pedido, **kwargs):
    """
    Dispara alerta admin quando pedido transiciona para ERRO.

    Usa cache para throttle de 1 hora por pedido para evitar spam
    em casos de múltiplas transições ERRO → REENVIO → ERRO.
    """
    # Apenas processa se status é ERRO
    if instance.status != PedidoStatus.ERRO:
        return

    # Throttle via cache
    cache_key = f"alert_sent:{instance.id}"
    if cache.get(cache_key):
        logger.debug(
            "Alert already sent for pedido",
            extra={
                "event": "alert_throttled",
                "pedido_id": str(instance.id),
            },
        )
        return

    # Marca no cache antes de disparar
    cache.set(cache_key, True, ALERT_THROTTLE_TTL)

    # Dispara task de alerta após commit
    from clama.notifications.tasks import enviar_alerta_admin_task

    pedido_id = str(instance.id)
    transaction.on_commit(lambda: enviar_alerta_admin_task.delay(pedido_id))

    logger.info(
        "Alert dispatched for pedido ERRO",
        extra={
            "event": "alert_dispatched",
            "pedido_id": pedido_id,
        },
    )
