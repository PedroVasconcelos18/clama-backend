"""
Testes do `turnstile_client` — verificação anti-robô (CAPTCHA invisível).
"""

from unittest.mock import MagicMock, patch

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings

from clama.freemium.services.turnstile_client import TurnstileClient


class TestTurnstileMockMode:
    @override_settings(TURNSTILE_SECRET_KEY="")
    def test_mock_mode_aceita_token_nao_vazio(self):
        client = TurnstileClient()
        assert client.mock_mode is True
        assert client.validate("qualquer-token-nao-vazio") is True

    @override_settings(TURNSTILE_SECRET_KEY="")
    def test_mock_mode_rejeita_token_vazio(self):
        client = TurnstileClient()
        assert client.validate("") is False

    @override_settings(TURNSTILE_SECRET_KEY="")
    def test_mock_mode_aceita_sandbox_token_da_cloudflare(self):
        client = TurnstileClient()
        assert client.validate("XXXX.DUMMY.TOKEN.XXXX") is True


class TestTurnstileRealMode:
    @override_settings(TURNSTILE_SECRET_KEY="real-secret-1234")
    def test_validate_real_chama_api_e_parsea_success(self):
        client = TurnstileClient()
        assert client.mock_mode is False

        fake_response = MagicMock()
        fake_response.status_code = 200
        fake_response.raise_for_status = MagicMock()
        fake_response.json.return_value = {"success": True}

        with patch(
            "clama.freemium.services.turnstile_client.requests.post",
            return_value=fake_response,
        ) as mocked_post:
            ok = client.validate("token-cliente", ip="203.0.113.5")

        assert ok is True
        mocked_post.assert_called_once()
        # Confirma que o secret e o response foram enviados como form-data.
        _, kwargs = mocked_post.call_args
        data = kwargs["data"]
        assert data["secret"] == "real-secret-1234"
        assert data["response"] == "token-cliente"
        assert data["remoteip"] == "203.0.113.5"

    @override_settings(TURNSTILE_SECRET_KEY="real-secret-1234")
    def test_validate_real_omite_remoteip_quando_none(self):
        client = TurnstileClient()
        fake_response = MagicMock()
        fake_response.status_code = 200
        fake_response.raise_for_status = MagicMock()
        fake_response.json.return_value = {"success": True}

        with patch(
            "clama.freemium.services.turnstile_client.requests.post",
            return_value=fake_response,
        ) as mocked_post:
            client.validate("tk", ip=None)

        _, kwargs = mocked_post.call_args
        assert "remoteip" not in kwargs["data"]

    @override_settings(TURNSTILE_SECRET_KEY="real-secret-1234")
    def test_validate_real_retorna_false_se_success_false(self):
        client = TurnstileClient()
        fake_response = MagicMock()
        fake_response.status_code = 200
        fake_response.raise_for_status = MagicMock()
        fake_response.json.return_value = {
            "success": False,
            "error-codes": ["invalid-input-response"],
        }
        with patch(
            "clama.freemium.services.turnstile_client.requests.post",
            return_value=fake_response,
        ):
            assert client.validate("token-ruim") is False


class TestTurnstileProdGuard:
    def test_prod_sem_secret_levanta_improperly_configured(self):
        """
        Sem secret + DEBUG=False + fora de testes → falha cedo (P-1 anti-bypass).

        Como rodamos sob pytest, precisamos forjar o detector de teste para
        retornar False para acionar o caminho de produção.
        """
        with override_settings(TURNSTILE_SECRET_KEY="", DEBUG=False), patch(
            "clama.freemium.services.turnstile_client._is_testing",
            return_value=False,
        ):
            with pytest.raises(ImproperlyConfigured):
                TurnstileClient()

    def test_prod_sem_secret_em_debug_e_mock_mode(self):
        """Em DEBUG, secret vazio cai em mock mode mesmo sem testes."""
        with override_settings(TURNSTILE_SECRET_KEY="", DEBUG=True), patch(
            "clama.freemium.services.turnstile_client._is_testing",
            return_value=False,
        ):
            client = TurnstileClient()
            assert client.mock_mode is True
