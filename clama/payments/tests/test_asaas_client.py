"""
Testes para o AsaasClient.
"""
from unittest.mock import MagicMock, patch

import pytest
import requests

from clama.payments.exceptions import AsaasIntegrationError
from clama.payments.services.asaas_client import AsaasClient


@pytest.fixture
def asaas_client():
    """Cliente Asaas com configurações de teste."""
    with patch("clama.payments.services.asaas_client.settings") as mock_settings:
        mock_settings.ASAAS_API_KEY = "test_api_key"
        mock_settings.ASAAS_BASE_URL = "https://sandbox.asaas.com/api/v3"
        return AsaasClient()


class TestAsaasClientCriarCliente:
    """Testes para o método criar_cliente."""

    def test_criar_cliente_success(self, asaas_client):
        """Criar cliente com sucesso retorna dict com id."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"id": "cus_12345", "name": "Maria Silva"}
        mock_response.raise_for_status.return_value = None

        with patch.object(asaas_client.session, "post", return_value=mock_response):
            result = asaas_client.criar_cliente(
                nome="Maria Silva",
                email="maria@example.com",
            )

        assert result["id"] == "cus_12345"
        assert result["name"] == "Maria Silva"

    def test_criar_cliente_with_cpf(self, asaas_client):
        """Criar cliente com CPF inclui no payload."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"id": "cus_12345"}
        mock_response.raise_for_status.return_value = None

        with patch.object(asaas_client.session, "post", return_value=mock_response) as mock_post:
            asaas_client.criar_cliente(
                nome="Maria Silva",
                email="maria@example.com",
                cpf_cnpj="12345678901",
            )

        call_kwargs = mock_post.call_args[1]
        assert call_kwargs["json"]["cpfCnpj"] == "12345678901"

    def test_criar_cliente_http_400_raises_immediately(self, asaas_client):
        """Erro 400 não retenta e levanta AsaasIntegrationError com upstream status/body."""
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.json.return_value = {
            "errors": [{"code": "invalid_cpfCnpj", "description": "CPF inválido"}]
        }
        http_error = requests.HTTPError(response=mock_response)
        mock_response.raise_for_status.side_effect = http_error

        with patch.object(asaas_client.session, "post", return_value=mock_response):
            with pytest.raises(AsaasIntegrationError) as exc_info:
                asaas_client.criar_cliente(
                    nome="Maria Silva",
                    email="maria@example.com",
                )

        assert exc_info.value.upstream_status == 400
        assert exc_info.value.upstream_body == {
            "errors": [{"code": "invalid_cpfCnpj", "description": "CPF inválido"}]
        }

    def test_criar_cliente_http_400_captures_non_json_body(self, asaas_client):
        """Se o body da Asaas não for JSON, captura texto truncado em 500 chars."""
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.json.side_effect = ValueError("not json")
        mock_response.text = "Plain text error"
        http_error = requests.HTTPError(response=mock_response)
        mock_response.raise_for_status.side_effect = http_error

        with patch.object(asaas_client.session, "post", return_value=mock_response):
            with pytest.raises(AsaasIntegrationError) as exc_info:
                asaas_client.criar_cliente(
                    nome="Maria Silva",
                    email="maria@example.com",
                )

        assert exc_info.value.upstream_status == 400
        assert exc_info.value.upstream_body == "Plain text error"


class TestAsaasClientCriarCobranca:
    """Testes para o método criar_cobranca."""

    def test_criar_cobranca_success(self, asaas_client):
        """Criar cobrança com sucesso retorna dict com id e invoiceUrl."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "id": "pay_12345",
            "invoiceUrl": "https://asaas.com/i/12345",
            "status": "PENDING",
        }
        mock_response.raise_for_status.return_value = None

        with patch.object(asaas_client.session, "post", return_value=mock_response):
            result = asaas_client.criar_cobranca(
                customer_id="cus_12345",
                valor_centavos=2000,
                descricao="Pedido de Oração",
                pedido_id="pedido-123",
            )

        assert result["id"] == "pay_12345"
        assert result["invoiceUrl"] == "https://asaas.com/i/12345"
        assert result["status"] == "PENDING"

    def test_criar_cobranca_converts_centavos_to_reais(self, asaas_client):
        """Valor em centavos é convertido para reais no payload."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"id": "pay_12345"}
        mock_response.raise_for_status.return_value = None

        with patch.object(asaas_client.session, "post", return_value=mock_response) as mock_post:
            asaas_client.criar_cobranca(
                customer_id="cus_12345",
                valor_centavos=2500,  # R$ 25,00
                descricao="Pedido de Oração",
                pedido_id="pedido-123",
            )

        call_kwargs = mock_post.call_args[1]
        assert call_kwargs["json"]["value"] == 25.0


class TestAsaasClientRetry:
    """Testes de retry do AsaasClient."""

    def test_retry_on_503_then_success(self, asaas_client):
        """503 retenta e sucesso na segunda tentativa."""
        # Primeira chamada: 503
        mock_response_503 = MagicMock()
        mock_response_503.status_code = 503
        http_error = requests.HTTPError(response=mock_response_503)
        mock_response_503.raise_for_status.side_effect = http_error

        # Segunda chamada: sucesso
        mock_response_200 = MagicMock()
        mock_response_200.status_code = 200
        mock_response_200.json.return_value = {"id": "cus_12345"}
        mock_response_200.raise_for_status.return_value = None

        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return mock_response_503
            return mock_response_200

        with patch.object(asaas_client.session, "post", side_effect=side_effect):
            with patch("clama.core.retry.time.sleep"):  # Skip actual sleep
                result = asaas_client.criar_cliente(
                    nome="Maria",
                    email="maria@example.com",
                )

        assert result["id"] == "cus_12345"
        assert call_count == 2

    def test_retry_exhausted_raises_error(self, asaas_client):
        """3 tentativas de 503 esgotam e levantam erro."""
        mock_response = MagicMock()
        mock_response.status_code = 503
        http_error = requests.HTTPError(response=mock_response)
        mock_response.raise_for_status.side_effect = http_error

        with patch.object(asaas_client.session, "post", return_value=mock_response):
            with patch("clama.core.retry.time.sleep"):  # Skip actual sleep
                with pytest.raises(requests.HTTPError):
                    asaas_client.criar_cliente(
                        nome="Maria",
                        email="maria@example.com",
                    )

    def test_connection_error_retries(self, asaas_client):
        """ConnectionError retenta."""
        call_count = 0

        # Primeira chamada: erro
        # Segunda chamada: sucesso
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"id": "cus_12345"}
        mock_response.raise_for_status.return_value = None

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise requests.ConnectionError("Connection failed")
            return mock_response

        with patch.object(asaas_client.session, "post", side_effect=side_effect):
            with patch("clama.core.retry.time.sleep"):
                result = asaas_client.criar_cliente(
                    nome="Maria",
                    email="maria@example.com",
                )

        assert result["id"] == "cus_12345"
        assert call_count == 2
