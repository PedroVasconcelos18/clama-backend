"""
ALTER `User.email_hash` para NOT NULL.

Roda DEPOIS do backfill (0005). Email é sempre presente (unique=True), então
todos os users têm hash válido após o backfill — safe pra apertar a coluna.

`cpf_hash` e `telefone_hash` ficam nullable porque users legacy/admin podem
não ter coletado esses dados. O signal `pre_save` mantém a sync para users
novos.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0006_backfill_freemium_used_at"),
    ]

    operations = [
        migrations.AlterField(
            model_name="user",
            name="email_hash",
            field=models.CharField(
                db_index=True,
                help_text="HMAC-SHA-256 do e-mail normalizado (Gmail canonical).",
                max_length=64,
                verbose_name="Hash do e-mail",
            ),
        ),
    ]
