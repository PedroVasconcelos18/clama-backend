"""
Testes para o endpoint GET /api/pedidos/{id}/.
"""
import uuid

import pytest
from django.core.cache import cache
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from clama.orders.tests.factories import PedidoFactory


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
def pedido():
    """Pedido para testes."""
    return PedidoFactory()


@pytest.mark.django_db
class TestPedidoStatusAPI:
    """Testes para consulta de status de pedidos."""

    def test_get_pedido_status_success(self, api_client, pedido):
        """GET válido retorna 200."""
        url = reverse("pedido-status", kwargs={"id": pedido.id})
        response = api_client.get(url)

        assert response.status_code == status.HTTP_200_OK

    def test_get_pedido_returns_public_fields(self, api_client, pedido):
        """Resposta deve conter apenas campos públicos."""
        url = reverse("pedido-status", kwargs={"id": pedido.id})
        response = api_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert "id" in response.data
        assert "status" in response.data
        assert "plano" in response.data  # Nome do plano
        assert "valor_reais_str" in response.data
        assert "canal_entrega" in response.data
        assert "created_at" in response.data

    def test_get_pedido_does_not_return_sensitive_data(self, api_client, pedido):
        """Resposta não deve conter dados sensíveis."""
        url = reverse("pedido-status", kwargs={"id": pedido.id})
        response = api_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert "nome" not in response.data
        assert "email" not in response.data
        assert "telefone" not in response.data
        assert "pedido_oracao" not in response.data
        assert "oracao_gerada" not in response.data

    def test_get_pedido_returns_plano_nome(self, api_client, pedido):
        """plano deve retornar o nome do plano, não o ID."""
        url = reverse("pedido-status", kwargs={"id": pedido.id})
        response = api_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert response.data["plano"] == pedido.plano.nome


@pytest.mark.django_db
class TestPedidoStatusNotFound:
    """Testes para pedido não encontrado."""

    def test_nonexistent_pedido_returns_404(self, api_client):
        """UUID inexistente retorna 404."""
        fake_uuid = uuid.uuid4()
        url = reverse("pedido-status", kwargs={"id": fake_uuid})
        response = api_client.get(url)

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_404_returns_pastoral_message(self, api_client):
        """404 deve conter mensagem pastoral."""
        fake_uuid = uuid.uuid4()
        url = reverse("pedido-status", kwargs={"id": fake_uuid})
        response = api_client.get(url)

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert "error" in response.data
        assert response.data["error"]["code"] == "not_found"
        assert "pastoral_message" in response.data["error"]


@pytest.mark.django_db
class TestPedidoStatusRateLimit:
    """Testes de rate limiting para consulta de status."""

    def test_rate_limit_blocks_after_60_requests(self, api_client, pedido):
        """61ª request deve ser bloqueada por rate limit."""
        url = reverse("pedido-status", kwargs={"id": pedido.id})

        # Fazer 61 requests - a 61ª deve ser bloqueada
        for i in range(61):
            response = api_client.get(url)
            if i < 60:
                assert response.status_code == status.HTTP_200_OK
            else:
                assert response.status_code == status.HTTP_429_TOO_MANY_REQUESTS
