"""
Tests do paywall em `POST /api/pedidos/` (spec G2.a backend, entregue via
spec lp-user-existence-gate em 2026-05-10).

Comportamento:
- Anônimo → 401 (DRF default IsAuthenticated; spec dizia 403, mas DRF
  retorna NotAuthenticated quando autenticadores estão configurados e nenhum
  passou — comportamento mais correto que 403 puro).
- Autenticado com `force_change_password=True` → 403 (IsCustomerPasswordCurrent).
- Autenticado normal → 201 com `pedido.user` setado a partir do `request.user`.
"""

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from clama.orders.models import CanalEntrega, Pedido
from clama.plans.tests.factories import PlanFactory

User = get_user_model()


@pytest.fixture
def plano_ativo():
    return PlanFactory(ativo=True, valor_centavos=2000)


@pytest.fixture
def valid_payload(plano_ativo):
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
class TestPedidoCreatePaywall:
    def test_anonimo_retorna_401(self, db, valid_payload):
        client = APIClient()
        url = reverse("pedido-create")
        response = client.post(url, valid_payload, format="json")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert not Pedido.objects.exists()

    def test_autenticado_force_change_password_retorna_403(
        self, db, valid_payload
    ):
        user = User.objects.create_user(
            email="force@example.com",
            password="Temp-Pass-1234!",
            force_change_password=True,
        )
        client = APIClient()
        client.force_authenticate(user=user)
        url = reverse("pedido-create")
        response = client.post(url, valid_payload, format="json")
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert response.data["error"]["code"] == "customer_force_change_password"
        assert not Pedido.objects.exists()

    def test_autenticado_ok_seta_user_no_pedido(self, db, valid_payload):
        user = User.objects.create_user(
            email="customer@example.com",
            password="Senha-Forte-12345!",
        )
        client = APIClient()
        client.force_authenticate(user=user)
        url = reverse("pedido-create")
        response = client.post(url, valid_payload, format="json")

        assert response.status_code == status.HTTP_201_CREATED
        pedido = Pedido.objects.get(id=response.data["id"])
        assert pedido.user_id == user.id

    def test_autenticado_admin_pode_criar_pedido(self, db, valid_payload):
        """
        Admin do Clama é IsAuthenticated. Esse caminho NÃO é o fluxo
        normal (admins não compram), mas não bloqueamos — o paywall foca
        em garantir que tem um user vinculado, não em bloquear roles.
        """
        admin = User.objects.create_user(
            email="admin@example.com",
            password="Senha-Forte-12345!",
            is_clama_admin=True,
        )
        client = APIClient()
        client.force_authenticate(user=admin)
        url = reverse("pedido-create")
        response = client.post(url, valid_payload, format="json")

        assert response.status_code == status.HTTP_201_CREATED
        pedido = Pedido.objects.get(id=response.data["id"])
        assert pedido.user_id == admin.id
