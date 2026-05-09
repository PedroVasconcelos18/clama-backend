"""
Testes da `IsCustomerPasswordCurrent` (G2.a).

Cenários:
- Usuário com `force_change_password=True` em `POST /api/pedidos/` → 403 pastoral.
- Usuário com `force_change_password=False` em `POST /api/pedidos/` → 201.
- Isenção: `POST /api/customer/auth/change-password/` aceita usuário com flag true.
- Isenção: `GET /api/customer/me/` aceita usuário com flag true.
"""

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from clama.orders.models import CanalEntrega
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


def _login(api_client, email, password):
    response = api_client.post(
        reverse("users:customer-login"),
        {"email": email, "password": password},
        format="json",
    )
    assert response.status_code == status.HTTP_200_OK, response.data
    return response.data["access"]


@pytest.mark.django_db
class TestPedidosForcePasswordCurrent:
    def test_user_com_flag_true_recebe_403_em_pedidos(
        self, api_client, valid_pedido_data
    ):
        User.objects.create_user(
            email="bia@example.com",
            password="TempPwd!#999",
            force_change_password=True,
        )
        access = _login(api_client, "bia@example.com", "TempPwd!#999")
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")

        url = reverse("pedido-create")
        response = api_client.post(url, valid_pedido_data, format="json")
        assert response.status_code == status.HTTP_403_FORBIDDEN
        # Mensagem pastoral.
        assert (
            response.data.get("error", {}).get("code")
            == "force_change_password"
        )
        assert "Troque sua senha" in response.data["error"]["pastoral_message"]

    def test_user_com_flag_false_recebe_201_em_pedidos(
        self, api_client, valid_pedido_data
    ):
        User.objects.create_user(
            email="alice@example.com",
            password="SenhaForte!123",
            force_change_password=False,
        )
        access = _login(api_client, "alice@example.com", "SenhaForte!123")
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")

        url = reverse("pedido-create")
        response = api_client.post(url, valid_pedido_data, format="json")
        assert response.status_code == status.HTTP_201_CREATED


@pytest.mark.django_db
class TestIsencoesIsCustomerPasswordCurrent:
    """change-password e /me/ são isentos da permission."""

    def test_change_password_aceita_user_com_flag_true(self, api_client):
        User.objects.create_user(
            email="bia@example.com",
            password="TempPwd!#999",
            force_change_password=True,
        )
        access = _login(api_client, "bia@example.com", "TempPwd!#999")
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")

        response = api_client.post(
            reverse("users:customer-change-password"),
            {"senha_atual": "TempPwd!#999", "nova_senha": "NovaSenhaForte!42"},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK

    def test_me_aceita_user_com_flag_true(self, api_client):
        User.objects.create_user(
            email="bia@example.com",
            password="TempPwd!#999",
            force_change_password=True,
        )
        access = _login(api_client, "bia@example.com", "TempPwd!#999")
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")

        response = api_client.get(reverse("users:customer-me"))
        assert response.status_code == status.HTTP_200_OK
        assert response.data["force_change_password"] is True


class TestIsCustomerPasswordCurrentStandalone:
    """
    P-10: defesa em profundidade — se alguém compor este permission SEM
    `IsAuthenticated` por engano, anônimo deve cair em negação (não em
    "passou silencioso"). Verificamos a unidade direto, sem precisar
    montar uma view.
    """

    def test_anonimo_recebe_false(self):
        from unittest.mock import MagicMock

        from clama_backend.users.permissions import IsCustomerPasswordCurrent

        permission = IsCustomerPasswordCurrent()
        request = MagicMock()
        request.user = None
        assert permission.has_permission(request, view=None) is False

    def test_anonymous_user_recebe_false(self):
        from unittest.mock import MagicMock

        from django.contrib.auth.models import AnonymousUser

        from clama_backend.users.permissions import IsCustomerPasswordCurrent

        permission = IsCustomerPasswordCurrent()
        request = MagicMock()
        request.user = AnonymousUser()
        assert permission.has_permission(request, view=None) is False
