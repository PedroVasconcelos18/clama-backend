"""
Migration pós-renegociação 2026-05-08:
- Cria o modelo `FreemiumConfirmationToken` para suportar o fluxo de
  double opt-in por e-mail (substitui OTP via WhatsApp do v1).

O token é opaco (`secrets.token_urlsafe(48)` truncado em 64 chars),
persistido com FK para o `Pedido`, TTL default 24h, single-use.
"""

import uuid

import django.db.models.deletion
from django.db import migrations, models

import clama.freemium.models


class Migration(migrations.Migration):

    dependencies = [
        ("freemium", "0002_drop_telefone_hash"),
        ("orders", "0005_pedido_aguardando_confirmacao"),
    ]

    operations = [
        migrations.CreateModel(
            name="FreemiumConfirmationToken",
            fields=[
                (
                    "created_at",
                    models.DateTimeField(auto_now_add=True),
                ),
                (
                    "updated_at",
                    models.DateTimeField(auto_now=True),
                ),
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "token",
                    models.CharField(
                        db_index=True,
                        help_text="secrets.token_urlsafe(48) truncado em 64 chars.",
                        max_length=64,
                        unique=True,
                        verbose_name="Token opaco",
                    ),
                ),
                (
                    "expires_at",
                    models.DateTimeField(
                        default=clama.freemium.models._default_expiracao,
                        help_text="Default: criação + 24h.",
                        verbose_name="Expira em",
                    ),
                ),
                (
                    "used_at",
                    models.DateTimeField(
                        blank=True,
                        null=True,
                        verbose_name="Usado em",
                    ),
                ),
                (
                    "ip_origem",
                    models.GenericIPAddressField(
                        blank=True,
                        null=True,
                        verbose_name="IP de origem",
                    ),
                ),
                (
                    "device_hash",
                    models.CharField(
                        blank=True,
                        default="",
                        max_length=128,
                        verbose_name="Device fingerprint",
                    ),
                ),
                (
                    "pedido",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="confirmation_tokens",
                        to="orders.pedido",
                        verbose_name="Pedido",
                    ),
                ),
            ],
            options={
                "verbose_name": "Token de confirmação freemium",
                "verbose_name_plural": "Tokens de confirmação freemium",
                "ordering": ["-created_at"],
            },
        ),
    ]
