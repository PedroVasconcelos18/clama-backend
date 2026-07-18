"""
Migração MP.3 — campos de pagamento agnósticos de provider (Mercado Pago).

Adiciona `Pedido.provider_payment_id` e `provider_checkout_url` (ambos nullable).
Migração puramente aditiva (NFR6). Os campos nascem nulos — NÃO há backfill de
`asaas_charge_id`/`asaas_invoice_url`, que são inválidos no Mercado Pago e fariam
o CheckoutView reusar um checkout Asaas morto. Os campos `asaas_*` são removidos
só em MP.7 (após o drain dos pedidos in-flight).
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("orders", "0006_pedido_oracao_email_sent_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="pedido",
            name="provider_payment_id",
            field=models.CharField(
                blank=True,
                max_length=120,
                null=True,
                verbose_name="ID do pagamento no gateway",
            ),
        ),
        migrations.AddField(
            model_name="pedido",
            name="provider_checkout_url",
            field=models.URLField(
                blank=True,
                null=True,
                verbose_name="URL de checkout do gateway",
            ),
        ),
    ]
