"""
Migração MP.3 — adiciona `MERCADO_PAGO` ao enum `WebhookProvider`.

`AlterField` gerado pela mudança de `choices` no campo `WebhookEvento.provider`.
É DB-noop (choices não são enforçados no nível do banco), mas versionado para
manter modelos e migrações em sincronia (`makemigrations --check`).
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("payments", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="webhookevento",
            name="provider",
            field=models.CharField(
                choices=[
                    ("ASAAS", "Asaas"),
                    ("ZAPI", "Z-API"),
                    ("MERCADO_PAGO", "Mercado Pago"),
                ],
                help_text="Provedor de origem do webhook",
                max_length=20,
            ),
        ),
    ]
