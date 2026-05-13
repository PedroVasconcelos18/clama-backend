"""
Testes do paywall em POST /api/pedidos/ (G2.a).

- Anônimo → 401 pastoral.
- Bearer customer válido → 201 com `Pedido.user == request.user` e
  `Pedido.eh_gratuito=False`.
"""

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from clama.orders.models import CanalEntrega, Pedido
from clama.plans.tests.factories import PlanFactory

User = get_user_model()


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def plano_ativo(db):
    return PlanFactory(ativo=True, valor_centavos=2000)


@pytest.fixture
def valid_pedido_data(plano_ativo):
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


@pytest.fixture
def customer_user(db):
    return User.objects.create_user(
        email="alice@example.com",
        password="SenhaForte!123",
        nome_completo="Alice",
    )


def _login(api_client, email, password):
    response = api_client.post(
        reverse("users:customer-login"),
        {"email": email, "password": password},
        format="json",
    )
    assert response.status_code == status.HTTP_200_OK, response.data
    return response.data["access"]


@pytest.mark.django_db
class TestPaywallPedidos:
    def test_anonimo_recebe_401(self, api_client, valid_pedido_data):
        """
        P-16: o 401 do paywall precisa ser pastoralizado — não a string
        genérica "Authentication credentials were not provided." do DRF.
        Verificamos formato `{ error: { code, message, pastoral_message } }`.
        """
        url = reverse("pedido-create")
        response = api_client.post(url, valid_pedido_data, format="json")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert "error" in response.data
        assert response.data["error"].get("code") == "not_authenticated"
        assert "pastoral_message" in response.data["error"]
        assert "Faça login" in response.data["error"]["pastoral_message"]

    def test_bearer_customer_recebe_201_e_seta_user(
        self, api_client, valid_pedido_data, customer_user
    ):
        access = _login(api_client, "alice@example.com", "SenhaForte!123")
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")

        url = reverse("pedido-create")
        response = api_client.post(url, valid_pedido_data, format="json")
        assert response.status_code == status.HTTP_201_CREATED, response.data

        pedido = Pedido.objects.get(id=response.data["id"])
        assert pedido.user_id == customer_user.id
        assert pedido.eh_gratuito is False

    def test_email_throttle_nao_pode_ser_burlado_via_payload_quando_autenticado(
        self, api_client, valid_pedido_data, customer_user
    ):
        """
        P-2 (G2.a hardening): com auth, o `EmailScopedThrottle` deve usar
        `request.user.email` — não o `email` do body. Caso contrário um
        cliente logado variaria o campo `email` em cada POST e burlaria
        o limite (5/hour). Este teste autentica e posta 6 pedidos com 6
        emails diferentes; a 6ª deve cair em 429.

        Nota: o `pedidos_create` (ScopedRateThrottle por IP) é 10/min, então
        não bate antes — é o `EmailScopedThrottle` (5/hour) que deve barrar.
        """
        access = _login(api_client, "alice@example.com", "SenhaForte!123")
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
        url = reverse("pedido-create")

        for i in range(5):
            data = {**valid_pedido_data, "email": f"variante{i}@example.com"}
            response = api_client.post(url, data, format="json")
            assert response.status_code in (
                status.HTTP_201_CREATED,
                status.HTTP_400_BAD_REQUEST,
            ), f"req {i+1} retornou {response.status_code}: {response.data}"

        # 6ª: throttle por user.email (alice@example.com) deve estourar.
        data = {**valid_pedido_data, "email": "variante5@example.com"}
        response = api_client.post(url, data, format="json")
        assert response.status_code == status.HTTP_429_TOO_MANY_REQUESTS

    def test_payload_user_id_no_body_e_ignorado(
        self, api_client, valid_pedido_data, customer_user
    ):
        """
        Defesa: tentativa de spoof do `user` via payload deve ser ignorada —
        o serializer fixa `validated_data['user'] = request.user`. (Nota: o
        ModelSerializer atual nem aceita `user` como input field, mas
        verificamos comportamento end-to-end.)
        """
        outro = User.objects.create_user(
            email="other@example.com", password="SenhaForte!123"
        )
        access = _login(api_client, "alice@example.com", "SenhaForte!123")
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")

        spoofed = {**valid_pedido_data, "user": outro.id}
        url = reverse("pedido-create")
        response = api_client.post(url, spoofed, format="json")
        assert response.status_code == status.HTTP_201_CREATED, response.data

        pedido = Pedido.objects.get(id=response.data["id"])
        assert pedido.user_id == customer_user.id
