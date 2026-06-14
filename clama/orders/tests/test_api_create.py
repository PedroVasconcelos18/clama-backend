"""
Testes para o endpoint POST /api/pedidos/.

Spec G2.a backend (entregue via spec lp-user-existence-gate em 2026-05-10):
o endpoint passou a exigir `IsAuthenticated + IsCustomerPasswordCurrent`.
Para isolar os testes existentes (validação, persistence, valor livre) da
regra de auth, o fixture `auth_customer` força um user autenticado em
todos os tests deste módulo. Cenários de paywall propriamente ditos
(401 anônimo, 403 force_change_password) ficam em test_paywall.py.
"""
import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from clama.orders.models import CanalEntrega, Pedido, PedidoStatus
from clama.plans.models import Complexidade, Plan
from clama.plans.tests.factories import PlanFactory

User = get_user_model()


@pytest.fixture(autouse=True)
def clear_cache():
    """Limpa o cache antes de cada teste para resetar rate limiting."""
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def customer_user(db):
    """User customer válido — usado pelo `api_client` autenticado."""
    return User.objects.create_user(
        email="customer@example.com",
        password="Senha-Forte-12345!",
    )


@pytest.fixture
def api_client(customer_user):
    """API client autenticado como customer (spec G2.a paywall)."""
    client = APIClient()
    client.force_authenticate(user=customer_user)
    return client


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
        "cpf_cnpj": "11144477735",
        "consent_aceito": True,
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
        """Valor abaixo de R$ 5,99 (599 centavos) retorna 400."""
        valid_pedido_data["valor_centavos"] = 598
        url = reverse("pedido-create")
        response = api_client.post(url, valid_pedido_data, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_valor_no_minimo_599_sucesso(self, api_client, valid_pedido_data):
        """Valor exatamente R$ 5,99 (599 centavos) é aceito (valor livre)."""
        valid_pedido_data["valor_centavos"] = 599
        valid_pedido_data.pop("plano", None)  # força inferência por valor livre
        url = reverse("pedido-create")
        response = api_client.post(url, valid_pedido_data, format="json")

        assert response.status_code == status.HTTP_201_CREATED

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
class TestPedidoCreateValorLivre:
    """Testes para criação via Valor Livre (sem plano explícito — backend infere)."""

    @pytest.fixture
    def tres_planos(self):
        """Três planos ativos (SIMPLES R$20, COM_VERSICULO R$50, COM_PROFECIA R$100)."""
        Plan.objects.all().delete()
        simples = PlanFactory(
            nome="Simples",
            valor_centavos=2000,
            complexidade=Complexidade.SIMPLES,
            ordem=1,
            ativo=True,
        )
        com_versiculo = PlanFactory(
            nome="Com versículo",
            valor_centavos=5000,
            complexidade=Complexidade.COM_VERSICULO,
            ordem=2,
            ativo=True,
        )
        com_profecia = PlanFactory(
            nome="Com profecia",
            valor_centavos=10000,
            complexidade=Complexidade.COM_PROFECIA_E_VERSICULOS,
            ordem=3,
            ativo=True,
        )
        return simples, com_versiculo, com_profecia

    def _base_data(self):
        return {
            "nome": "Maria Silva",
            "email": "maria@example.com",
            "telefone": "(11) 99999-8888",
            "idade": 35,
            "sexo": "feminino",
            "pedido_oracao": "Peço oração pela minha família.",
            "canal_entrega": CanalEntrega.EMAIL,
            "cpf_cnpj": "12345678909",
            "consent_aceito": True,
        }

    def test_valor_livre_20_mapeia_simples(self, api_client, tres_planos):
        """R$20 sem plano → SIMPLES."""
        simples, _, _ = tres_planos
        data = {**self._base_data(), "valor_centavos": 2000}
        url = reverse("pedido-create")
        response = api_client.post(url, data, format="json")

        assert response.status_code == status.HTTP_201_CREATED
        pedido = Pedido.objects.get(id=response.data["id"])
        assert pedido.plano == simples
        assert pedido.plano.complexidade == Complexidade.SIMPLES
        assert pedido.valor_centavos == 2000

    def test_valor_livre_75_mapeia_com_versiculo(self, api_client, tres_planos):
        """R$75 sem plano → COM_VERSICULO (par abaixo: R$50)."""
        _, com_versiculo, _ = tres_planos
        data = {**self._base_data(), "valor_centavos": 7500}
        url = reverse("pedido-create")
        response = api_client.post(url, data, format="json")

        assert response.status_code == status.HTTP_201_CREATED
        pedido = Pedido.objects.get(id=response.data["id"])
        assert pedido.plano == com_versiculo
        assert pedido.plano.complexidade == Complexidade.COM_VERSICULO
        assert pedido.valor_centavos == 7500

    def test_valor_livre_150_mapeia_com_profecia(self, api_client, tres_planos):
        """R$150 sem plano → COM_PROFECIA (par abaixo: R$100)."""
        _, _, com_profecia = tres_planos
        data = {**self._base_data(), "valor_centavos": 15000}
        url = reverse("pedido-create")
        response = api_client.post(url, data, format="json")

        assert response.status_code == status.HTTP_201_CREATED
        pedido = Pedido.objects.get(id=response.data["id"])
        assert pedido.plano == com_profecia
        assert pedido.plano.complexidade == Complexidade.COM_PROFECIA_E_VERSICULOS
        assert pedido.valor_centavos == 15000

    def test_valor_livre_abaixo_minimo_retorna_400(self, api_client, tres_planos):
        """Valor < R$ 5,99 deve ser rejeitado mesmo sem plano explícito."""
        data = {**self._base_data(), "valor_centavos": 500}
        url = reverse("pedido-create")
        response = api_client.post(url, data, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_valor_livre_com_plano_null_aceito(self, api_client, tres_planos):
        """Enviar plano=null explicitamente também deve funcionar."""
        simples, _, _ = tres_planos
        data = {**self._base_data(), "valor_centavos": 2000, "plano": None}
        url = reverse("pedido-create")
        response = api_client.post(url, data, format="json")

        assert response.status_code == status.HTTP_201_CREATED
        pedido = Pedido.objects.get(id=response.data["id"])
        assert pedido.plano == simples


@pytest.mark.django_db
class TestPedidoCreateRateLimit:
    """Testes de rate limiting para criação de pedidos."""

    def test_rate_limit_blocks_after_limit(self, api_client, valid_pedido_data):
        """
        11ª request deve ser bloqueada por `pedidos_create=10/min` (IP-scoped).

        Cada request usa um email diferente pra evitar o `EmailScopedThrottle`
        (5/hour por email) — isolando o teste no throttle de IP que o nome do
        teste implica.
        """
        url = reverse("pedido-create")

        for i in range(11):
            # Email único por request — isola do EmailScopedThrottle.
            payload = dict(valid_pedido_data)
            payload["email"] = f"user{i}@example.com"
            response = api_client.post(url, payload, format="json")
            if i < 10:
                assert response.status_code in [
                    status.HTTP_201_CREATED,
                    status.HTTP_400_BAD_REQUEST,
                ], f"Request {i+1} retornou {response.status_code} inesperado"
            else:
                assert (
                    response.status_code == status.HTTP_429_TOO_MANY_REQUESTS
                ), f"Request {i+1} deveria ser bloqueada, mas retornou {response.status_code}"
