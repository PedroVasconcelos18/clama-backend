"""
Testes para o endpoint POST /api/pedidos/{id}/checkout/.
"""
from unittest.mock import MagicMock, patch

import pytest
from django.core.cache import cache
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from clama.orders.models import PedidoStatus
from clama.orders.tests.factories import PedidoFactory
from clama.payments.exceptions import AsaasIntegrationError


@pytest.fixture(autouse=True)
def clear_cache():
    """Limpa o cache antes de cada teste para resetar rate limiting."""
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def api_client():
    """API client para testes."""
    return APIClient()


@pytest.fixture
def pedido_aguardando():
    """Pedido no status AGUARDANDO_PAGAMENTO."""
    return PedidoFactory(status=PedidoStatus.AGUARDANDO_PAGAMENTO)


@pytest.fixture
def pedido_pago():
    """Pedido no status PAGO."""
    return PedidoFactory(status=PedidoStatus.PAGO)


@pytest.fixture
def pedido_gerando():
    """Pedido no status GERANDO_ORACAO."""
    return PedidoFactory(status=PedidoStatus.GERANDO_ORACAO)


@pytest.fixture
def mock_asaas_client():
    """Mock do AsaasClient que retorna sucesso."""
    with patch("clama.payments.api.views.AsaasClient") as mock_class:
        mock_instance = MagicMock()
        mock_instance.criar_cliente.return_value = {"id": "cus_12345"}
        mock_instance.criar_cobranca.return_value = {
            "id": "pay_12345",
            "invoiceUrl": "https://sandbox.asaas.com/i/12345",
            "status": "PENDING",
        }
        mock_class.return_value = mock_instance
        yield mock_instance


@pytest.mark.django_db
class TestCheckoutHappyPath:
    """Testes do fluxo feliz do checkout."""

    def test_checkout_success_returns_200(
        self, api_client, pedido_aguardando, mock_asaas_client
    ):
        """Checkout com sucesso retorna 200."""
        url = reverse("pedido-checkout", kwargs={"id": pedido_aguardando.id})
        response = api_client.post(url)

        assert response.status_code == status.HTTP_200_OK

    def test_checkout_success_returns_checkout_url(
        self, api_client, pedido_aguardando, mock_asaas_client
    ):
        """Resposta deve conter checkout_url e pedido_id."""
        url = reverse("pedido-checkout", kwargs={"id": pedido_aguardando.id})
        response = api_client.post(url)

        assert response.status_code == status.HTTP_200_OK
        assert "checkout_url" in response.data
        assert "pedido_id" in response.data
        assert response.data["checkout_url"] == "https://sandbox.asaas.com/i/12345"
        assert response.data["pedido_id"] == str(pedido_aguardando.id)

    def test_checkout_creates_asaas_customer(
        self, api_client, pedido_aguardando, mock_asaas_client
    ):
        """Checkout deve chamar criar_cliente com nome, email e cpf_cnpj."""
        url = reverse("pedido-checkout", kwargs={"id": pedido_aguardando.id})
        api_client.post(url)

        mock_asaas_client.criar_cliente.assert_called_once_with(
            nome=pedido_aguardando.nome,
            email=pedido_aguardando.email,
            cpf_cnpj=pedido_aguardando.cpf_cnpj,
        )

    def test_checkout_creates_asaas_charge(
        self, api_client, pedido_aguardando, mock_asaas_client
    ):
        """Checkout deve chamar criar_cobranca com dados corretos."""
        url = reverse("pedido-checkout", kwargs={"id": pedido_aguardando.id})
        api_client.post(url)

        mock_asaas_client.criar_cobranca.assert_called_once()
        call_kwargs = mock_asaas_client.criar_cobranca.call_args[1]
        assert call_kwargs["customer_id"] == "cus_12345"
        assert call_kwargs["valor_centavos"] == pedido_aguardando.valor_centavos
        assert "Pedido Clama #" in call_kwargs["descricao"]

    def test_checkout_persists_asaas_ids(
        self, api_client, pedido_aguardando, mock_asaas_client
    ):
        """Checkout deve persistir asaas_charge_id e asaas_invoice_url."""
        url = reverse("pedido-checkout", kwargs={"id": pedido_aguardando.id})
        api_client.post(url)

        pedido_aguardando.refresh_from_db()
        assert pedido_aguardando.asaas_charge_id == "pay_12345"
        assert pedido_aguardando.asaas_invoice_url == "https://sandbox.asaas.com/i/12345"


@pytest.mark.django_db
class TestCheckoutErrors:
    """Testes de erros do checkout."""

    def test_pedido_not_found_returns_404(self, api_client, mock_asaas_client):
        """Pedido inexistente retorna 404."""
        url = reverse(
            "pedido-checkout",
            kwargs={"id": "00000000-0000-0000-0000-000000000000"},
        )
        response = api_client.post(url)

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert response.data["error"]["code"] == "not_found"

    def test_pedido_pago_returns_409(
        self, api_client, pedido_pago, mock_asaas_client
    ):
        """Pedido já pago retorna 409."""
        url = reverse("pedido-checkout", kwargs={"id": pedido_pago.id})
        response = api_client.post(url)

        assert response.status_code == status.HTTP_409_CONFLICT
        assert response.data["error"]["code"] == "pedido_ja_pago"
        assert "já foi pago" in response.data["error"]["pastoral_message"]

    def test_pedido_gerando_returns_409(
        self, api_client, pedido_gerando, mock_asaas_client
    ):
        """Pedido em status GERANDO_ORACAO retorna 409."""
        url = reverse("pedido-checkout", kwargs={"id": pedido_gerando.id})
        response = api_client.post(url)

        assert response.status_code == status.HTTP_409_CONFLICT

    def test_asaas_4xx_returns_422(self, api_client, pedido_aguardando):
        """Asaas respondendo 4xx (dado inválido) retorna 422, não 502."""
        with patch("clama.payments.api.views.AsaasClient") as mock_class:
            mock_instance = MagicMock()
            mock_instance.criar_cliente.side_effect = AsaasIntegrationError(
                message="Asaas rejected CPF",
                upstream_status=400,
                upstream_body={"errors": [{"code": "invalid_cpfCnpj"}]},
            )
            mock_class.return_value = mock_instance

            url = reverse("pedido-checkout", kwargs={"id": pedido_aguardando.id})
            response = api_client.post(url)

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        assert response.data["error"]["code"] == "asaas_integration_error"
        assert "soluço" in response.data["error"]["pastoral_message"]

    def test_asaas_5xx_returns_503(self, api_client, pedido_aguardando):
        """Asaas respondendo 5xx / rede indisponível retorna 503."""
        with patch("clama.payments.api.views.AsaasClient") as mock_class:
            mock_instance = MagicMock()
            # upstream_status None simula rede/timeout após retries esgotados
            mock_instance.criar_cliente.side_effect = AsaasIntegrationError(
                message="Connection error",
                upstream_status=None,
            )
            mock_class.return_value = mock_instance

            url = reverse("pedido-checkout", kwargs={"id": pedido_aguardando.id})
            response = api_client.post(url)

        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        assert response.data["error"]["code"] == "asaas_integration_error"

    def test_asaas_error_keeps_pedido_status(self, api_client, pedido_aguardando):
        """Erro do Asaas não altera status do pedido."""
        original_status = pedido_aguardando.status

        with patch("clama.payments.api.views.AsaasClient") as mock_class:
            mock_instance = MagicMock()
            mock_instance.criar_cliente.side_effect = AsaasIntegrationError(
                message="Connection error"
            )
            mock_class.return_value = mock_instance

            url = reverse("pedido-checkout", kwargs={"id": pedido_aguardando.id})
            api_client.post(url)

        pedido_aguardando.refresh_from_db()
        assert pedido_aguardando.status == original_status

    def test_pedido_sem_cpf_returns_422(self, api_client, mock_asaas_client):
        """Pedido sem CPF retorna 422 antes de chamar a Asaas."""
        pedido = PedidoFactory(
            status=PedidoStatus.AGUARDANDO_PAGAMENTO,
            cpf_cnpj="",
        )

        url = reverse("pedido-checkout", kwargs={"id": pedido.id})
        response = api_client.post(url)

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        assert response.data["error"]["code"] == "cpf_cnpj_obrigatorio"
        mock_asaas_client.criar_cliente.assert_not_called()


@pytest.mark.django_db(transaction=True)
class TestCheckoutIdempotency:
    """Testes de idempotência: reuso de cobrança existente."""

    def test_reuses_existing_charge_without_calling_asaas(
        self, api_client, mock_asaas_client
    ):
        """Pedido com charge_id+invoice_url já setados reutiliza e não chama a Asaas."""
        pedido = PedidoFactory(
            status=PedidoStatus.AGUARDANDO_PAGAMENTO,
            asaas_charge_id="pay_existing",
            asaas_invoice_url="https://sandbox.asaas.com/i/existing",
        )

        url = reverse("pedido-checkout", kwargs={"id": pedido.id})
        response = api_client.post(url)

        assert response.status_code == status.HTTP_200_OK
        assert response.data["checkout_url"] == "https://sandbox.asaas.com/i/existing"
        mock_asaas_client.criar_cliente.assert_not_called()
        mock_asaas_client.criar_cobranca.assert_not_called()

    def test_partial_state_does_not_trigger_reuse(
        self, api_client, mock_asaas_client
    ):
        """charge_id sem invoice_url (estado inconsistente) não dispara reuso."""
        pedido = PedidoFactory(
            status=PedidoStatus.AGUARDANDO_PAGAMENTO,
            asaas_charge_id="pay_existing",
            asaas_invoice_url="",
        )

        url = reverse("pedido-checkout", kwargs={"id": pedido.id})
        api_client.post(url)

        mock_asaas_client.criar_cliente.assert_called_once()
        mock_asaas_client.criar_cobranca.assert_called_once()


@pytest.mark.django_db
class TestCheckoutDescricaoNoPII:
    """Testes para garantir que descrição não contém PII."""

    def test_descricao_contains_only_id_prefix(
        self, api_client, pedido_aguardando, mock_asaas_client
    ):
        """Descrição deve conter apenas prefixo do ID, sem PII."""
        url = reverse("pedido-checkout", kwargs={"id": pedido_aguardando.id})
        api_client.post(url)

        call_kwargs = mock_asaas_client.criar_cobranca.call_args[1]
        descricao = call_kwargs["descricao"]

        # Deve conter prefixo do ID
        assert str(pedido_aguardando.id)[:8] in descricao

        # Não deve conter PII
        assert pedido_aguardando.nome not in descricao
        assert pedido_aguardando.email not in descricao
