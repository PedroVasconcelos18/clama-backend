"""
Data migration: popula `email_hash`, `cpf_hash`, `telefone_hash` para todos
os Users existentes a partir dos campos plaintext.

Idempotente — re-execução produz o mesmo resultado (HMAC determinístico).
Tolera Users sem CPF/telefone (legacy admin). Email é sempre presente
(unique=True), então `email_hash` fica preenchido para todos.

Nota: os campos `cpf_cnpj` e `telefone` são `EncryptedCharField` — Django
descriptografa transparentemente ao acessar `.cpf_cnpj` / `.telefone`. Como
o decrypt depende do app domain (não funciona via `RunSQL`), iteramos via
ORM. Para bases pequenas (atual: <100 users em pre-prod) isso é trivial;
se a base crescer, refatorar para chunked iteration.
"""

from django.db import migrations


def backfill_hashes(apps, schema_editor):
    """
    Recalcula hashes a partir do plaintext atual.

    Usa o User concreto (não o histórico) porque precisamos do EncryptedField
    descriptografando os bytes. Isso significa que mudanças futuras no model
    podem mudar o comportamento desta migration — aceitável dado que
    rodamos uma vez por ambiente. Em base com decrypt key trocada, hashes
    velhos ficam inválidos de qualquer jeito (vide spec).
    """
    from clama.freemium.hashing import (
        hash_cpf_cnpj,
        hash_email,
        hash_telefone,
    )
    from clama_backend.users.models import User

    for user in User.objects.all():
        user.email_hash = hash_email(user.email or "")
        user.cpf_hash = hash_cpf_cnpj(user.cpf_cnpj or "")
        user.telefone_hash = hash_telefone(user.telefone or "")
        user.save(update_fields=["email_hash", "cpf_hash", "telefone_hash"])


def reverse_noop(apps, schema_editor):
    """Reverter o backfill é safe-noop — a 0004 (RemoveField) zera os campos."""
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0004_add_hash_columns_and_freemium_used_at"),
    ]

    operations = [
        migrations.RunPython(backfill_hashes, reverse_noop),
    ]
