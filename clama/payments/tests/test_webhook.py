"""
Testes para o webhook POST /api/webhooks/asaas/.
"""
from unittest.mock import patch

import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from clama.orders.models import PedidoStatus
from clama.orders.tests.factories import PedidoFactory


@pytest.fixture
def api_client():
    """API client para testes."""
    return APIClient()


@pytest.fixture
def pedido_aguardando():
    """Pedido no status AGUARDANDO_PAGAMENTO com asaas_charge_id."""
    return PedidoFactory(
        status=PedidoStatus.AGUARDANDO_PAGAMENTO,
        asaas_charge_id="pay_12345",
    )


@pytest.fixture
def pedido_pago():
    """Pedido no status PAGO."""
    return PedidoFactory(
        status=PedidoStatus.PAGO,
        asaas_charge_id="pay_67890",
    )


@pytest.fixture
def payment_confirmed_payload():
    """Payload de evento PAYMENT_CONFIRMED."""
    return {
        "event": "PAYMENT_CONFIRMED",
        "payment": {
            "id": "pay_12345",
            "customer": "cus_abc123",
            "value": 50.00,
            "status": "CONFIRMED",
        },
    }


@pytest.fixture
def payment_received_payload():
    """Payload de evento PAYMENT_RECEIVED."""
    return {
        "event": "PAYMENT_RECEIVED",
        "payment": {
            "id": "pay_12345",
            "customer": "cus_abc123",
            "value": 50.00,
            "status": "RECEIVED",
        },
    }


@pytest.mark.django_db
class TestAsaasWebhookHappyPath:
    """Testes do fluxo feliz do webhook."""

    def test_payment_confirmed_returns_200(
        self, api_client, pedido_aguardando, payment_confirmed_payload
    ):
        """PAYMENT_CONFIRMED retorna 200."""
        url = reverse("asaas-webhook")

        with patch("clama.orders.tasks.gerar_oracao_task.delay") as mock_task:
            response = api_client.post(url, payment_confirmed_payload, format="json")

        assert response.status_code == status.HTTP_200_OK
        assert response.data["ok"] is True

    def test_payment_confirmed_changes_status_to_pago(
        self, api_client, pedido_aguardando, payment_confirmed_payload
    ):
        """PAYMENT_CONFIRMED muda status para PAGO."""
        url = reverse("asaas-webhook")

        with patch("clama.orders.tasks.gerar_oracao_task.delay"):
            api_client.post(url, payment_confirmed_payload, format="json")

        pedido_aguardando.refresh_from_db()
        assert pedido_aguardando.status == PedidoStatus.PAGO

    def test_payment_confirmed_dispatches_task(
        self, api_client, pedido_aguardando, payment_confirmed_payload
    ):
        """PAYMENT_CONFIRMED dispara gerar_oracao_task."""
        url = reverse("asaas-webhook")

        with patch("clama.orders.tasks.gerar_oracao_task.delay") as mock_task:
            api_client.post(url, payment_confirmed_payload, format="json")

        mock_task.assert_called_once_with(str(pedido_aguardando.id))

    def test_payment_received_also_works(
        self, api_client, pedido_aguardando, payment_received_payload
    ):
        """PAYMENT_RECEIVED também muda status para PAGO."""
        url = reverse("asaas-webhook")

        with patch("clama.orders.tasks.gerar_oracao_task.delay"):
            response = api_client.post(url, payment_received_payload, format="json")

        assert response.status_code == status.HTTP_200_OK
        pedido_aguardando.refresh_from_db()
        assert pedido_aguardando.status == PedidoStatus.PAGO


@pytest.mark.django_db
class TestAsaasWebhookIgnoredEvents:
    """Testes para eventos ignorados."""

    def test_unknown_event_returns_200(self, api_client):
        """Evento desconhecido retorna 200 sem erro."""
        url = reverse("asaas-webhook")
        payload = {
            "event": "PAYMENT_OVERDUE",
            "payment": {"id": "pay_99999"},
        }

        response = api_client.post(url, payload, format="json")

        assert response.status_code == status.HTTP_200_OK
        assert response.data["ok"] is True

    def test_unknown_event_does_not_change_pedido(
        self, api_client, pedido_aguardando
    ):
        """Evento desconhecido não altera pedido."""
        url = reverse("asaas-webhook")
        payload = {
            "event": "PAYMENT_OVERDUE",
            "payment": {"id": pedido_aguardando.asaas_charge_id},
        }
        original_status = pedido_aguardando.status

        response = api_client.post(url, payload, format="json")

        assert response.status_code == status.HTTP_200_OK
        pedido_aguardando.refresh_from_db()
        assert pedido_aguardando.status == original_status


@pytest.mark.django_db
class TestAsaasWebhookPedidoNotFound:
    """Testes para pedido não encontrado."""

    def test_pedido_not_found_returns_200(self, api_client):
        """Pedido não encontrado retorna 200 (evita retry infinito)."""
        url = reverse("asaas-webhook")
        payload = {
            "event": "PAYMENT_CONFIRMED",
            "payment": {"id": "pay_nonexistent"},
        }

        response = api_client.post(url, payload, format="json")

        assert response.status_code == status.HTTP_200_OK
        assert response.data["ok"] is True


@pytest.mark.django_db
class TestAsaasWebhookIdempotency:
    """Testes de idempotência básica."""

    def test_pedido_already_pago_returns_200(
        self, api_client, pedido_pago
    ):
        """Pedido já PAGO retorna 200 sem disparar task."""
        url = reverse("asaas-webhook")
        payload = {
            "event": "PAYMENT_CONFIRMED",
            "payment": {"id": pedido_pago.asaas_charge_id},
        }

        with patch("clama.orders.tasks.gerar_oracao_task.delay") as mock_task:
            response = api_client.post(url, payload, format="json")

        assert response.status_code == status.HTTP_200_OK
        mock_task.assert_not_called()

    def test_pedido_already_pago_does_not_change(
        self, api_client, pedido_pago
    ):
        """Pedido já PAGO não muda de status."""
        url = reverse("asaas-webhook")
        payload = {
            "event": "PAYMENT_CONFIRMED",
            "payment": {"id": pedido_pago.asaas_charge_id},
        }

        with patch("clama.orders.tasks.gerar_oracao_task.delay"):
            api_client.post(url, payload, format="json")

        pedido_pago.refresh_from_db()
        assert pedido_pago.status == PedidoStatus.PAGO

    def test_double_webhook_is_idempotent(
        self, api_client, pedido_aguardando, payment_confirmed_payload
    ):
        """Dois webhooks consecutivos só processam uma vez."""
        url = reverse("asaas-webhook")

        with patch("clama.orders.tasks.gerar_oracao_task.delay") as mock_task:
            # Primeiro webhook
            response1 = api_client.post(url, payment_confirmed_payload, format="json")
            # Segundo webhook (mesmo payment_id)
            response2 = api_client.post(url, payment_confirmed_payload, format="json")

        assert response1.status_code == status.HTTP_200_OK
        assert response2.status_code == status.HTTP_200_OK
        # Task só deve ter sido chamada uma vez
        assert mock_task.call_count == 1


@pytest.mark.django_db
class TestAsaasWebhookMalformedPayload:
    """Testes para payloads malformados."""

    def test_missing_event_returns_200(self, api_client):
        """Payload sem event retorna 200 (evento ignorado)."""
        url = reverse("asaas-webhook")
        payload = {"payment": {"id": "pay_12345"}}

        response = api_client.post(url, payload, format="json")

        assert response.status_code == status.HTTP_200_OK

    def test_missing_payment_returns_200(self, api_client):
        """Payload sem payment retorna 200 (graceful handling)."""
        url = reverse("asaas-webhook")
        payload = {"event": "PAYMENT_CONFIRMED"}

        response = api_client.post(url, payload, format="json")

        assert response.status_code == status.HTTP_200_OK

    def test_empty_payload_returns_200(self, api_client):
        """Payload vazio retorna 200."""
        url = reverse("asaas-webhook")

        response = api_client.post(url, {}, format="json")

        assert response.status_code == status.HTTP_200_OK
