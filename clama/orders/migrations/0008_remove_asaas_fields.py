"""
Migração MP.7 — remove os campos Asaas do Pedido (corte big-bang).

`RemoveField` de `asaas_charge_id` e `asaas_invoice_url`. Aplicada no corte,
após o drain dos pedidos in-flight (virada com servidor desligado, sem
pagamentos Asaas pendentes). Os campos `provider_*` (MP.3) já os substituem.
"""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("orders", "0007_add_provider_payment_fields"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="pedido",
            name="asaas_charge_id",
        ),
        migrations.RemoveField(
            model_name="pedido",
            name="asaas_invoice_url",
        ),
    ]
