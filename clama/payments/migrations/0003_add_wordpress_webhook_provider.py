"""Story 3.2 — acrescenta `WORDPRESS` ao enum `WebhookProvider`.

`AlterField` gerado pela mudança de `choices`. É DB-noop (choices não são
enforçados no banco), mas versionado para manter modelos e migrações em
sincronia (`makemigrations --check`). Mesmo padrão da 0002.

Não há tabela nova para o webhook do WordPress: `provider` faz parte da
`UniqueConstraint` de idempotência (`uq_webhook_event_provider_id`), então o
mesmo `WebhookEvento` serve.
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("payments", "0002_add_mercado_pago_webhook_provider"),
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
                    ("WORDPRESS", "WordPress"),
                ],
                help_text="Provedor de origem do webhook",
                max_length=20,
            ),
        ),
    ]
