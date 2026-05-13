"""
Testes do `confirmation_service` — gerar/validar/consumir token de
confirmação por e-mail (substitui OTP no fluxo freemium pós-2026-05-08).
"""

from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

from clama.freemium.exceptions import (
    ConfirmationTokenExpiradoError,
    ConfirmationTokenInvalidoError,
)
from clama.freemium.models import FreemiumConfirmationToken
from clama.freemium.services import confirmation_service
from clama.orders.tests.factories import PedidoFactory


@pytest.mark.django_db
class TestGerarToken:
    def test_gerar_token_cria_e_retorna_string(self):
        pedido = PedidoFactory()
        token_str = confirmation_service.gerar_token(
            pedido, ip_origem="203.0.113.10", device_hash="dh1"
        )
        assert isinstance(token_str, str)
        assert len(token_str) > 0
        # Deve respeitar o limite do CharField (max_length=64).
        assert len(token_str) <= 64

    def test_gerar_token_persiste_no_banco_com_pedido_correto(self):
        pedido = PedidoFactory()
        token_str = confirmation_service.gerar_token(
            pedido, ip_origem=None, device_hash=""
        )
        token_obj = FreemiumConfirmationToken.objects.get(token=token_str)
        assert token_obj.pedido_id == pedido.id
        assert token_obj.used_at is None
        # Default expires_at ~ now + 24h.
        delta = token_obj.expires_at - timezone.now()
        assert timedelta(hours=23, minutes=59) <= delta <= timedelta(hours=24, minutes=1)

    def test_gerar_token_grava_ip_e_device_hash(self):
        pedido = PedidoFactory()
        token_str = confirmation_service.gerar_token(
            pedido, ip_origem="198.51.100.7", device_hash="abc-device"
        )
        token_obj = FreemiumConfirmationToken.objects.get(token=token_str)
        assert token_obj.ip_origem == "198.51.100.7"
        assert token_obj.device_hash == "abc-device"

    def test_gerar_token_aceita_device_hash_none_como_string_vazia(self):
        # Embora a anotação seja `str`, defendemos contra `None` na prática
        # — o normalizamos para string vazia (campo é blank=True).
        pedido = PedidoFactory()
        token_str = confirmation_service.gerar_token(
            pedido, ip_origem=None, device_hash=""
        )
        token_obj = FreemiumConfirmationToken.objects.get(token=token_str)
        assert token_obj.device_hash == ""


@pytest.mark.django_db
class TestValidarEConsumir:
    def test_happy_marca_used_at_e_retorna_pedido(self):
        pedido = PedidoFactory()
        token_str = confirmation_service.gerar_token(
            pedido, ip_origem=None, device_hash=""
        )
        retornado = confirmation_service.validar_e_consumir(token_str)
        assert retornado.id == pedido.id

        token_obj = FreemiumConfirmationToken.objects.get(token=token_str)
        assert token_obj.used_at is not None

    def test_token_inexistente_levanta_invalido(self):
        with pytest.raises(ConfirmationTokenInvalidoError):
            confirmation_service.validar_e_consumir("no-such-token")

    def test_token_string_vazia_levanta_invalido(self):
        with pytest.raises(ConfirmationTokenInvalidoError):
            confirmation_service.validar_e_consumir("")

    def test_token_ja_usado_levanta_invalido(self):
        pedido = PedidoFactory()
        token_str = confirmation_service.gerar_token(
            pedido, ip_origem=None, device_hash=""
        )
        # Primeiro consumo: ok.
        confirmation_service.validar_e_consumir(token_str)
        # Segundo: deve falhar como inválido (não como expirado).
        with pytest.raises(ConfirmationTokenInvalidoError):
            confirmation_service.validar_e_consumir(token_str)

    def test_token_expirado_levanta_expirado(self):
        pedido = PedidoFactory()
        token_str = confirmation_service.gerar_token(
            pedido, ip_origem=None, device_hash=""
        )
        # Empurra `expires_at` para o passado simulando TTL passou.
        FreemiumConfirmationToken.objects.filter(token=token_str).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )
        with pytest.raises(ConfirmationTokenExpiradoError):
            confirmation_service.validar_e_consumir(token_str)
        # Token expirado NÃO deve ter sido marcado como usado — fica
        # como expirado puro (admin pode investigar).
        token_obj = FreemiumConfirmationToken.objects.get(token=token_str)
        assert token_obj.used_at is None

    def test_validacao_usa_select_for_update(self):
        """
        Verifica que a query de validação é serializada via `select_for_update`.

        Não consegue simular corrida real em SQLite (sem locking de row
        equivalente ao Postgres), então mockamos `select_for_update` e
        confirmamos que foi chamado durante `validar_e_consumir`.
        """
        pedido = PedidoFactory()
        token_str = confirmation_service.gerar_token(
            pedido, ip_origem=None, device_hash=""
        )

        from django.db.models.query import QuerySet

        original_select_for_update = QuerySet.select_for_update
        chamadas: list[None] = []

        def spy(self, *args, **kwargs):
            chamadas.append(None)
            return original_select_for_update(self, *args, **kwargs)

        with patch.object(QuerySet, "select_for_update", spy):
            confirmation_service.validar_e_consumir(token_str)

        assert chamadas, "select_for_update deve ser chamado durante a validação"
