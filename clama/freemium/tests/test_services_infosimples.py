"""
Testes para o `InfosimplesClient`.

Cobertura:
- Modo mock (token vazio): retorna ATIVO sem chamar a API.
- Parsing de respostas (REGULAR, SUSPENSA, CANCELADA, code != 200).
- Retry behavior em 5xx e ConnectionError.
"""

from unittest.mock import MagicMock, patch

import pytest
import requests

from clama.freemium.exceptions import InfosimplesError
from clama.freemium.services.infosimples_client import (
    STATUS_ATIVO,
    STATUS_CANCELADO,
    STATUS_INEXISTENTE,
    STATUS_SUSPENSO,
    InfosimplesClient,
)


@pytest.fixture
def cliente_real():
    """Cliente com token configurado (não-mock)."""
    with patch(
        "clama.freemium.services.infosimples_client.settings"
    ) as mock_settings:
        mock_settings.INFOSIMPLES_TOKEN = "real_token_for_test"
        mock_settings.INFOSIMPLES_BASE_URL = (
            "https://api.infosimples.com/api/v2/consultas/receita-federal"
        )
        yield InfosimplesClient()


class TestModoMock:
    def test_token_vazio_ativa_modo_mock(self):
        with patch(
            "clama.freemium.services.infosimples_client.settings"
        ) as mock_settings:
            mock_settings.INFOSIMPLES_TOKEN = ""
            mock_settings.INFOSIMPLES_BASE_URL = "https://x"
            cliente = InfosimplesClient()
        assert cliente.mock_mode is True

    def test_mock_retorna_ativo_sem_chamar_api(self):
        with patch(
            "clama.freemium.services.infosimples_client.settings"
        ) as mock_settings:
            mock_settings.INFOSIMPLES_TOKEN = ""
            mock_settings.INFOSIMPLES_BASE_URL = "https://x"
            cliente = InfosimplesClient()

        with patch(
            "clama.freemium.services.infosimples_client.requests.post"
        ) as mock_post:
            resultado = cliente.consultar_cpf_cnpj("123.456.789-09")

        assert resultado == {"status": STATUS_ATIVO, "nome": "MOCK PESSOA"}
        mock_post.assert_not_called()


class TestParsing:
    @pytest.mark.parametrize(
        "situacao,esperado",
        [
            ("REGULAR", STATUS_ATIVO),
            ("ATIVA", STATUS_ATIVO),
            ("SUSPENSA", STATUS_SUSPENSO),
            ("CANCELADA", STATUS_CANCELADO),
            ("BAIXADA", STATUS_CANCELADO),
            ("NULA", STATUS_CANCELADO),
            ("DESCONHECIDA", STATUS_INEXISTENTE),
        ],
    )
    def test_parse_situacao_cadastral(self, cliente_real, situacao, esperado):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "code": 200,
            "data": [{"situacao_cadastral": situacao, "nome": "Fulano"}],
        }
        mock_response.raise_for_status.return_value = None

        with patch(
            "clama.freemium.services.infosimples_client.requests.post",
            return_value=mock_response,
        ):
            resultado = cliente_real.consultar_cpf_cnpj("12345678909")

        assert resultado["status"] == esperado
        if esperado == STATUS_ATIVO:
            assert resultado["nome"] == "Fulano"

    def test_code_nao_200_retorna_inexistente(self, cliente_real):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"code": 612, "data": []}
        mock_response.raise_for_status.return_value = None

        with patch(
            "clama.freemium.services.infosimples_client.requests.post",
            return_value=mock_response,
        ):
            resultado = cliente_real.consultar_cpf_cnpj("12345678909")
        assert resultado["status"] == STATUS_INEXISTENTE
        assert resultado["nome"] is None

    def test_data_vazia_retorna_inexistente(self, cliente_real):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"code": 200, "data": []}
        mock_response.raise_for_status.return_value = None

        with patch(
            "clama.freemium.services.infosimples_client.requests.post",
            return_value=mock_response,
        ):
            resultado = cliente_real.consultar_cpf_cnpj("12345678909")
        assert resultado["status"] == STATUS_INEXISTENTE


class TestEndpointSelection:
    def test_cpf_usa_endpoint_cpf(self, cliente_real):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "code": 200,
            "data": [{"situacao_cadastral": "REGULAR"}],
        }
        mock_response.raise_for_status.return_value = None

        with patch(
            "clama.freemium.services.infosimples_client.requests.post",
            return_value=mock_response,
        ) as mock_post:
            cliente_real.consultar_cpf_cnpj("12345678909")
        url = mock_post.call_args[0][0]
        assert url.endswith("/cpf")

    def test_cnpj_usa_endpoint_cnpj(self, cliente_real):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "code": 200,
            "data": [{"situacao_cadastral": "ATIVA", "razao_social": "Acme"}],
        }
        mock_response.raise_for_status.return_value = None

        with patch(
            "clama.freemium.services.infosimples_client.requests.post",
            return_value=mock_response,
        ) as mock_post:
            cliente_real.consultar_cpf_cnpj("12345678000199")
        url = mock_post.call_args[0][0]
        assert url.endswith("/cnpj")


class TestRetry:
    def test_retry_em_503_e_sucesso_em_seguida(self, cliente_real):
        mock_503 = MagicMock()
        mock_503.status_code = 503
        http_error = requests.HTTPError(response=mock_503)
        mock_503.raise_for_status.side_effect = http_error

        mock_200 = MagicMock()
        mock_200.status_code = 200
        mock_200.json.return_value = {
            "code": 200,
            "data": [{"situacao_cadastral": "REGULAR", "nome": "Fulano"}],
        }
        mock_200.raise_for_status.return_value = None

        chamadas = {"n": 0}

        def side_effect(*args, **kwargs):
            chamadas["n"] += 1
            if chamadas["n"] == 1:
                return mock_503
            return mock_200

        with patch(
            "clama.freemium.services.infosimples_client.requests.post",
            side_effect=side_effect,
        ):
            with patch("clama.core.retry.time.sleep"):
                resultado = cliente_real.consultar_cpf_cnpj("12345678909")

        assert resultado["status"] == STATUS_ATIVO
        assert chamadas["n"] == 2

    def test_retry_em_connection_error(self, cliente_real):
        mock_200 = MagicMock()
        mock_200.status_code = 200
        mock_200.json.return_value = {
            "code": 200,
            "data": [{"situacao_cadastral": "REGULAR"}],
        }
        mock_200.raise_for_status.return_value = None

        chamadas = {"n": 0}

        def side_effect(*args, **kwargs):
            chamadas["n"] += 1
            if chamadas["n"] == 1:
                raise requests.ConnectionError("boom")
            return mock_200

        with patch(
            "clama.freemium.services.infosimples_client.requests.post",
            side_effect=side_effect,
        ):
            with patch("clama.core.retry.time.sleep"):
                resultado = cliente_real.consultar_cpf_cnpj("12345678909")

        assert resultado["status"] == STATUS_ATIVO
        assert chamadas["n"] == 2

    def test_retry_esgotado_propaga_http_error(self, cliente_real):
        mock_503 = MagicMock()
        mock_503.status_code = 503
        http_error = requests.HTTPError(response=mock_503)
        mock_503.raise_for_status.side_effect = http_error

        with patch(
            "clama.freemium.services.infosimples_client.requests.post",
            return_value=mock_503,
        ):
            with patch("clama.core.retry.time.sleep"):
                with pytest.raises(requests.HTTPError):
                    cliente_real.consultar_cpf_cnpj("12345678909")


class TestErroGenericoRequests:
    def test_request_exception_inesperado_levanta_infosimples_error(
        self, cliente_real
    ):
        with patch(
            "clama.freemium.services.infosimples_client.requests.post",
            side_effect=requests.exceptions.SSLError("ssl boom"),
        ):
            with patch("clama.core.retry.time.sleep"):
                with pytest.raises(
                    (requests.exceptions.SSLError, InfosimplesError)
                ):
                    cliente_real.consultar_cpf_cnpj("12345678909")
