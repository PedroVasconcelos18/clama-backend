"""
Migration pós-renegociação 2026-05-08:
- Adiciona o status `AGUARDANDO_CONFIRMACAO_EMAIL` na TextChoices `Status` do
  Pedido (double opt-in por e-mail substitui o OTP via WhatsApp do v1).
- Adiciona o campo `Pedido.device_hash` para registrar o hash do device
  fingerprint coletado no frontend (anti-fraude observacional no MVP).
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("orders", "0004_pedido_freemium"),
    ]

    operations = [
        migrations.AlterField(
            model_name="pedido",
            name="status",
            field=models.CharField(
                choices=[
                    ("aguardando_pagamento", "Aguardando pagamento"),
                    (
                        "aguardando_confirmacao_email",
                        "Aguardando confirmação por e-mail",
                    ),
                    ("pago", "Pago"),
                    ("gerando_oracao", "Gerando oração"),
                    ("oracao_gerada", "Oração gerada"),
                    ("enviada", "Enviada"),
                    ("aguardando_reenvio", "Aguardando reenvio"),
                    ("erro", "Erro"),
                ],
                default="aguardando_pagamento",
                max_length=40,
                verbose_name="Status",
            ),
        ),
        migrations.AddField(
            model_name="pedido",
            name="device_hash",
            field=models.CharField(
                blank=True,
                default="",
                max_length=128,
                verbose_name="hash do device fingerprint",
            ),
        ),
    ]
