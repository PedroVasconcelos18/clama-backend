"""
Data migration: popula `User.freemium_used_at` para users que já consumiram
o pedido gratuito (saga G1 antiga).

Estratégia: para cada User com pedidos `eh_gratuito=True` linkados, seta
`freemium_used_at = min(Pedido.created_at)`. Filtra por `user__isnull=False`
para evitar pedidos cancelados/órfãos sem user vinculado.
"""

from django.db import migrations
from django.db.models import Min


def backfill_freemium_used_at(apps, schema_editor):
    User = apps.get_model("users", "User")
    Pedido = apps.get_model("orders", "Pedido")

    # Agrupa pelo user_id e pega o created_at mais antigo dos pedidos gratuitos.
    qs = (
        Pedido.objects.filter(eh_gratuito=True, user__isnull=False)
        .values("user_id")
        .annotate(first_at=Min("created_at"))
    )
    for row in qs:
        User.objects.filter(pk=row["user_id"]).update(
            freemium_used_at=row["first_at"]
        )


def reverse_noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0005_backfill_user_hashes"),
        # Garante que `Pedido.user` já existe e está populado antes de ler.
        ("orders", "0006_pedido_oracao_email_sent_at"),
    ]

    operations = [
        migrations.RunPython(backfill_freemium_used_at, reverse_noop),
    ]
