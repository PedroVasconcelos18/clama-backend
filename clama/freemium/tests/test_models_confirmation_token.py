"""
Testes do model `FreemiumConfirmationToken`.

Valida criação, default de `expires_at` (24h), ordering, str repr e o
unique constraint do `token`.
"""

from datetime import timedelta

import pytest
from django.db import IntegrityError
from django.utils import timezone

from clama.freemium.models import (
    CONFIRMATION_TOKEN_TTL,
    FreemiumConfirmationToken,
)
from clama.orders.tests.factories import PedidoFactory


@pytest.mark.django_db
class TestFreemiumConfirmationTokenModel:
    def test_pode_criar_token(self):
        pedido = PedidoFactory()
        token = FreemiumConfirmationToken.objects.create(
            token="a" * 40,
            pedido=pedido,
        )
        assert token.id is not None
        assert token.pedido == pedido
        assert token.used_at is None

    def test_default_expires_at_aproximadamente_24h(self):
        pedido = PedidoFactory()
        antes = timezone.now()
        token = FreemiumConfirmationToken.objects.create(
            token="b" * 40,
            pedido=pedido,
        )
        depois = timezone.now()

        # `expires_at` deve estar no intervalo [antes + TTL, depois + TTL].
        assert token.expires_at >= antes + CONFIRMATION_TOKEN_TTL - timedelta(seconds=2)
        assert token.expires_at <= depois + CONFIRMATION_TOKEN_TTL + timedelta(seconds=2)
        # E deve estar muito próximo de 24h (com folga pequena).
        delta = token.expires_at - antes
        assert timedelta(hours=23, minutes=59) <= delta <= timedelta(hours=24, minutes=1)

    def test_token_unique(self):
        pedido = PedidoFactory()
        FreemiumConfirmationToken.objects.create(
            token="c" * 40,
            pedido=pedido,
        )
        with pytest.raises(IntegrityError):
            FreemiumConfirmationToken.objects.create(
                token="c" * 40,
                pedido=PedidoFactory(),
            )

    def test_str_representation(self):
        pedido = PedidoFactory()
        token = FreemiumConfirmationToken.objects.create(
            token="abcdefgh1234567890",
            pedido=pedido,
        )
        assert "FreemiumConfirmationToken" in str(token)
        # Prefixo dos primeiros 8 chars deve aparecer.
        assert "abcdefgh" in str(token)

    def test_ordering_descendente_por_created_at(self):
        pedido = PedidoFactory()
        primeiro = FreemiumConfirmationToken.objects.create(
            token="d" * 40,
            pedido=pedido,
        )
        segundo = FreemiumConfirmationToken.objects.create(
            token="e" * 40,
            pedido=pedido,
        )
        ordenados = list(FreemiumConfirmationToken.objects.all())
        # O mais novo (segundo) vem primeiro.
        assert ordenados[0] == segundo
        assert ordenados[1] == primeiro

    def test_pode_armazenar_ip_e_device_hash(self):
        pedido = PedidoFactory()
        token = FreemiumConfirmationToken.objects.create(
            token="f" * 40,
            pedido=pedido,
            ip_origem="203.0.113.42",
            device_hash="x" * 64,
        )
        token.refresh_from_db()
        assert token.ip_origem == "203.0.113.42"
        assert token.device_hash == "x" * 64

    def test_used_at_pode_ser_setado(self):
        pedido = PedidoFactory()
        agora = timezone.now()
        token = FreemiumConfirmationToken.objects.create(
            token="g" * 40,
            pedido=pedido,
        )
        token.used_at = agora
        token.save(update_fields=["used_at"])
        token.refresh_from_db()
        assert token.used_at is not None
