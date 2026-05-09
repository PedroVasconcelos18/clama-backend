"""
G2.a — adiciona `User.freemium_used_at` (DateTimeField nullable, indexed) e
faz backfill para Users criados pela saga freemium antes desta migration.

Backfill: para cada User que possui ao menos um `Pedido` com `eh_gratuito=True`,
seta `freemium_used_at = min(Pedido.created_at)` desses pedidos. Reverse
migration zera o campo de volta para `None` (idempotente).
"""

from django.db import migrations, models
from django.db.models import Min


def backfill_freemium_used_at(apps, schema_editor):
    """
    Para cada User com Pedido.eh_gratuito=True, define freemium_used_at =
    min(Pedido.created_at) dentre os pedidos grátis. Não toca em Users sem
    pedido grátis (campo permanece NULL).
    """
    User = apps.get_model("users", "User")
    Pedido = apps.get_model("orders", "Pedido")

    # Agrupa pedidos grátis por user_id e pega o created_at mínimo.
    agregados = (
        Pedido.objects.filter(eh_gratuito=True, user__isnull=False)
        .values("user_id")
        .annotate(primeiro=Min("created_at"))
    )

    for row in agregados:
        User.objects.filter(pk=row["user_id"]).update(
            freemium_used_at=row["primeiro"]
        )


def reverse_freemium_used_at(apps, schema_editor):
    """Zera o campo (volta ao estado pré-backfill)."""
    User = apps.get_model("users", "User")
    User.objects.update(freemium_used_at=None)


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0003_freemium_user_fields"),
        # Dependência explícita: o backfill agrupa Pedidos por `user_id`. A FK
        # `Pedido.user` foi adicionada em `orders/0004_pedido_freemium`, então
        # exigimos essa migration antes de rodar o data migration.
        ("orders", "0004_pedido_freemium"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="freemium_used_at",
            field=models.DateTimeField(
                blank=True,
                db_index=True,
                null=True,
                verbose_name="Usou freemium em",
            ),
        ),
        migrations.RunPython(
            backfill_freemium_used_at,
            reverse_code=reverse_freemium_used_at,
        ),
    ]
