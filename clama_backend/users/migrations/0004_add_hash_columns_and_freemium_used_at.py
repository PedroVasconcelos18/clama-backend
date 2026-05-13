"""
Adiciona colunas hash (email/cpf/telefone) + freemium_used_at ao User.

Schema apenas. O backfill dos hashes a partir dos campos plaintext
existentes vem na 0005, e o ALTER NOT NULL do `email_hash` na 0007
(depois do backfill).

`freemium_used_at` é populado pela 0006 a partir do `min(Pedido.created_at)`
agrupado por user (eh_gratuito=True).
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0003_freemium_user_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="email_hash",
            field=models.CharField(
                blank=True,
                db_index=True,
                help_text="HMAC-SHA-256 do e-mail normalizado (Gmail canonical).",
                max_length=64,
                null=True,
                verbose_name="Hash do e-mail",
            ),
        ),
        migrations.AddField(
            model_name="user",
            name="cpf_hash",
            field=models.CharField(
                blank=True,
                db_index=True,
                help_text="HMAC-SHA-256 do CPF/CNPJ (somente dígitos).",
                max_length=64,
                null=True,
                verbose_name="Hash do CPF/CNPJ",
            ),
        ),
        migrations.AddField(
            model_name="user",
            name="telefone_hash",
            field=models.CharField(
                blank=True,
                db_index=True,
                help_text="HMAC-SHA-256 do telefone (somente dígitos).",
                max_length=64,
                null=True,
                verbose_name="Hash do telefone",
            ),
        ),
        migrations.AddField(
            model_name="user",
            name="freemium_used_at",
            field=models.DateTimeField(
                blank=True,
                db_index=True,
                null=True,
                verbose_name="Pedido gratuito consumido em",
            ),
        ),
    ]
