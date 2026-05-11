"""
Data migration: popula `FreemiumBlacklist.telefone_hash` para entries
existentes a partir do telefone do Pedido associado ao User criado pela
saga.

Heurística de matching (não há FK direta blacklist→pedido, só através do
user/CPF):
- Para cada User com `pedidos.eh_gratuito=True` (filhos via FK), pega o
  telefone do primeiro Pedido com `eh_gratuito=True`.
- Procura na blacklist a entry cujo `cpf_hash` bate com `hash_cpf_cnpj
  (user.cpf_cnpj)` (1:1 desde a saga).
- Se encontra, popula `telefone_hash`.

Idempotente — re-run com hashes já populados é no-op.
Tolera blacklist entries sem match (admin manual, etc) — ficam com NULL.
"""

from django.db import migrations


def backfill_telefone_hash(apps, schema_editor):
    from clama.freemium.hashing import hash_cpf_cnpj, hash_telefone
    from clama.freemium.models import FreemiumBlacklist
    from clama_backend.users.models import User

    # Itera users que consumiram freemium (têm pedido gratuito). Para cada,
    # pega o telefone do pedido gratuito mais antigo (proxy do que foi
    # submetido na saga).
    users_freemium = User.objects.filter(pedidos__eh_gratuito=True).distinct()
    for user in users_freemium:
        pedido = (
            user.pedidos.filter(eh_gratuito=True)
            .order_by("created_at")
            .first()
        )
        if pedido is None or not pedido.telefone:
            continue

        cpf_h = hash_cpf_cnpj(user.cpf_cnpj or "")
        telefone_h = hash_telefone(pedido.telefone)

        FreemiumBlacklist.objects.filter(cpf_hash=cpf_h).update(
            telefone_hash=telefone_h
        )


def reverse_noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("freemium", "0004_add_telefone_hash"),
        # Garante que `User.cpf_hash` etc já existem (proxy de "users
        # totalmente migrado").
        ("users", "0007_email_hash_not_null"),
    ]

    operations = [
        migrations.RunPython(backfill_telefone_hash, reverse_noop),
    ]
