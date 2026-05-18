"""
Data migration: popula `User.idade` / `User.sexo` a partir do pedido MAIS
RECENTE de cada customer.

Esses campos servem só pra pré-preencher o form de novo pedido na /conta
(não são identidade — cada Pedido mantém sua própria idade/sexo, pois a
oração pode ser pra terceiros). O backfill usa o último pedido como melhor
palpite do destinatário padrão. Idempotente e reversível (reverse zera).
"""

from django.db import migrations


def backfill_idade_sexo(apps, schema_editor):
    User = apps.get_model("users", "User")
    Pedido = apps.get_model("orders", "Pedido")

    user_ids = (
        Pedido.objects.filter(user__isnull=False)
        .values_list("user_id", flat=True)
        .distinct()
    )
    for uid in user_ids:
        ultimo = (
            Pedido.objects.filter(user_id=uid)
            .order_by("-created_at")
            .first()
        )
        if ultimo is None:
            continue
        updates = {}
        if ultimo.idade is not None:
            updates["idade"] = ultimo.idade
        if ultimo.sexo:
            updates["sexo"] = ultimo.sexo
        if updates:
            User.objects.filter(pk=uid).update(**updates)


def reverse_zera(apps, schema_editor):
    User = apps.get_model("users", "User")
    User.objects.update(idade=None, sexo="")


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0009_user_idade_user_sexo"),
        ("orders", "0006_pedido_oracao_email_sent_at"),
    ]

    operations = [
        migrations.RunPython(backfill_idade_sexo, reverse_zera),
    ]
