"""
Testes para o endpoint POST /api/pedidos/.
"""
import pytest
from django.core.cache import cache
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from clama.orders.models import CanalEntrega, Pedido, PedidoStatus
from clama.plans.tests.factories import PlanFactory


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
def plano_ativo():
    """Plano ativo para testes."""
    return PlanFactory(ativo=True, valor_centavos=2000)


@pytest.fixture
def plano_inativo():
    """Plano inativo para testes."""
    return PlanFactory(ativo=False, valor_centavos=2000)


@pytest.fixture
def valid_pedido_data(plano_ativo):
    """Dados válidos para criar um pedido."""
    return {
        "nome": "Maria Silva",
        "email": "maria@example.com",
        "telefone": "(11) 99999-8888",
        "idade": 35,
        "sexo": "feminino",
        "pedido_oracao": "Peço oração pela minha família.",
        "plano": str(plano_ativo.id),
        "valor_centavos": 2000,
        "canal_entrega": CanalEntrega.EMAIL,
    }


@pytest.mark.django_db
class TestPedidoCreateAPI:
    """Testes para criação de pedidos."""

    def test_create_pedido_success(self, api_client, valid_pedido_data):
        """Criar pedido com dados válidos retorna 201."""
        url = reverse("pedido-create")
        response = api_client.post(url, valid_pedido_data, format="json")

        assert response.status_code == status.HTTP_201_CREATED
        assert "id" in response.data
        assert response.data["status"] == PedidoStatus.AGUARDANDO_PAGAMENTO

    def test_create_pedido_returns_id_and_status(self, api_client, valid_pedido_data):
        """Resposta deve conter id, status e valor_reais_str."""
        url = reverse("pedido-create")
        response = api_client.post(url, valid_pedido_data, format="json")

        assert response.status_code == status.HTTP_201_CREATED
        assert "id" in response.data
        assert "status" in response.data
        assert "valor_reais_str" in response.data
        assert "canal_entrega" in response.data
        assert "created_at" in response.data

    def test_create_pedido_does_not_return_sensitive_data(
        self, api_client, valid_pedido_data
    ):
        """Resposta não deve conter dados sensíveis."""
        url = reverse("pedido-create")
        response = api_client.post(url, valid_pedido_data, format="json")

        assert response.status_code == status.HTTP_201_CREATED
        assert "nome" not in response.data
        assert "email" not in response.data
        assert "telefone" not in response.data
        assert "pedido_oracao" not in response.data

    def test_create_pedido_persists_correctly(self, api_client, valid_pedido_data):
        """Pedido deve ser persistido com dados corretos."""
        url = reverse("pedido-create")
        response = api_client.post(url, valid_pedido_data, format="json")

        assert response.status_code == status.HTTP_201_CREATED

        pedido = Pedido.objects.get(id=response.data["id"])
        assert pedido.nome == "Maria Silva"
        assert pedido.email == "maria@example.com"
        assert pedido.status == PedidoStatus.AGUARDANDO_PAGAMENTO


@pytest.mark.django_db
class TestPedidoCreateValidation:
    """Testes de validação para criação de pedidos."""

    def test_missing_nome_returns_400(self, api_client, valid_pedido_data):
        """Nome faltando retorna 400."""
        del valid_pedido_data["nome"]
        url = reverse("pedido-create")
        response = api_client.post(url, valid_pedido_data, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_nome_too_short_returns_400(self, api_client, valid_pedido_data):
        """Nome com menos de 2 caracteres retorna 400."""
        valid_pedido_data["nome"] = "A"
        url = reverse("pedido-create")
        response = api_client.post(url, valid_pedido_data, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_missing_email_returns_400(self, api_client, valid_pedido_data):
        """Email faltando retorna 400."""
        del valid_pedido_data["email"]
        url = reverse("pedido-create")
        response = api_client.post(url, valid_pedido_data, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_invalid_email_returns_400(self, api_client, valid_pedido_data):
        """Email inválido retorna 400."""
        valid_pedido_data["email"] = "not-an-email"
        url = reverse("pedido-create")
        response = api_client.post(url, valid_pedido_data, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_valor_below_minimum_returns_400(self, api_client, valid_pedido_data):
        """Valor abaixo de R$20 (2000 centavos) retorna 400."""
        valid_pedido_data["valor_centavos"] = 1999
        url = reverse("pedido-create")
        response = api_client.post(url, valid_pedido_data, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_whatsapp_without_telefone_returns_400(self, api_client, valid_pedido_data):
        """WhatsApp sem telefone retorna 400."""
        valid_pedido_data["canal_entrega"] = CanalEntrega.WHATSAPP
        valid_pedido_data["telefone"] = ""
        url = reverse("pedido-create")
        response = api_client.post(url, valid_pedido_data, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_whatsapp_with_telefone_succeeds(self, api_client, valid_pedido_data):
        """WhatsApp com telefone deve funcionar."""
        valid_pedido_data["canal_entrega"] = CanalEntrega.WHATSAPP
        valid_pedido_data["telefone"] = "(11) 99999-8888"
        url = reverse("pedido-create")
        response = api_client.post(url, valid_pedido_data, format="json")

        assert response.status_code == status.HTTP_201_CREATED

    def test_inactive_plano_returns_400(
        self, api_client, valid_pedido_data, plano_inativo
    ):
        """Plano inativo retorna 400."""
        valid_pedido_data["plano"] = str(plano_inativo.id)
        url = reverse("pedido-create")
        response = api_client.post(url, valid_pedido_data, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_nonexistent_plano_returns_400(self, api_client, valid_pedido_data):
        """Plano inexistente retorna 400."""
        valid_pedido_data["plano"] = "00000000-0000-0000-0000-000000000000"
        url = reverse("pedido-create")
        response = api_client.post(url, valid_pedido_data, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
class TestPedidoCreateRateLimit:
    """Testes de rate limiting para criação de pedidos."""

    def test_rate_limit_blocks_after_limit(self, api_client, valid_pedido_data):
        """11ª request deve ser bloqueada por rate limit."""
        url = reverse("pedido-create")

        # Fazer 11 requests - a 11ª deve ser bloqueada
        for i in range(11):
            response = api_client.post(url, valid_pedido_data, format="json")
            if i < 10:
                # Primeiras 10 devem passar
                assert response.status_code in [
                    status.HTTP_201_CREATED,
                    status.HTTP_400_BAD_REQUEST,
                ], f"Request {i+1} retornou {response.status_code} inesperado"
            else:
                # 11ª deve ser bloqueada
                assert (
                    response.status_code == status.HTTP_429_TOO_MANY_REQUESTS
                ), f"Request {i+1} deveria ser bloqueada, mas retornou {response.status_code}"
