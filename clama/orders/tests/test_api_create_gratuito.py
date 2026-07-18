"""
Testes para o endpoint POST /api/pedidos/gratuito/.

Fluxo gratuito autenticado (card "Gratuito" em Minha Conta): cria o pedido
já como `eh_gratuito=True`, em `GERANDO_ORACAO`, sem gateway de pagamento, e dispara a
geração da oração via `transaction.on_commit`. Sem trava freemium.
"""
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from clama.freemium.tests.factories import get_or_create_plano_gratuito
from clama.orders.models import CanalEntrega, Pedido, PedidoStatus

User = get_user_model()


@pytest.fixture(autouse=True)
def clear_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def customer_user(db):
    return User.objects.create_user(
        email="customer@example.com",
        password="Senha-Forte-12345!",
    )


@pytest.fixture
def api_client(customer_user):
    client = APIClient()
    client.force_authenticate(user=customer_user)
    return client


@pytest.fixture
def plano_gratuito(db):
    return get_or_create_plano_gratuito()


@pytest.fixture
def valid_data():
    return {
        "nome": "Maria Silva",
        "email": "maria@example.com",
        "telefone": "(11) 99999-8888",
        "idade": 35,
        "sexo": "feminino",
        "pedido_oracao": "Peço oração pela minha família.",
        "canal_entrega": CanalEntrega.EMAIL,
        "cpf_cnpj": "11144477735",
        "consent_aceito": True,
    }


@pytest.mark.django_db
class TestPedidoCreateGratuito:
    def test_cria_gratuito_e_dispara_geracao(
        self, api_client, customer_user, plano_gratuito, valid_data,
        django_capture_on_commit_callbacks,
    ):
        url = reverse("pedido-create-gratuito")

        with patch(
            "clama.prayer_generation.tasks.gerar_oracao_task.delay"
        ) as mock_gerar:
            with django_capture_on_commit_callbacks(execute=True):
                response = api_client.post(url, valid_data, format="json")

        assert response.status_code == status.HTTP_201_CREATED
        pedido = Pedido.objects.get(id=response.data["id"])
        assert pedido.eh_gratuito is True
        assert pedido.valor_centavos == 0
        assert pedido.status == PedidoStatus.GERANDO_ORACAO
        assert pedido.plano_id == plano_gratuito.id
        assert pedido.user_id == customer_user.id
        mock_gerar.assert_called_once_with(str(pedido.id))

    def test_sem_consent_retorna_400(self, api_client, plano_gratuito, valid_data):
        valid_data["consent_aceito"] = False
        url = reverse("pedido-create-gratuito")
        response = api_client.post(url, valid_data, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_cpf_invalido_retorna_400(self, api_client, plano_gratuito, valid_data):
        valid_data["cpf_cnpj"] = "12345678900"
        url = reverse("pedido-create-gratuito")
        response = api_client.post(url, valid_data, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_whatsapp_sem_telefone_retorna_400(
        self, api_client, plano_gratuito, valid_data
    ):
        valid_data["canal_entrega"] = CanalEntrega.WHATSAPP
        valid_data["telefone"] = ""
        url = reverse("pedido-create-gratuito")
        response = api_client.post(url, valid_data, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_ignora_plano_e_valor_do_payload(
        self, api_client, plano_gratuito, valid_data,
        django_capture_on_commit_callbacks,
    ):
        """Mesmo que o cliente injete plano/valor, o backend força gratuito."""
        valid_data["valor_centavos"] = 5000
        valid_data["plano"] = "ignored"
        url = reverse("pedido-create-gratuito")

        with patch("clama.prayer_generation.tasks.gerar_oracao_task.delay"):
            with django_capture_on_commit_callbacks(execute=True):
                response = api_client.post(url, valid_data, format="json")

        assert response.status_code == status.HTTP_201_CREATED
        pedido = Pedido.objects.get(id=response.data["id"])
        assert pedido.valor_centavos == 0
        assert pedido.plano_id == plano_gratuito.id

    def test_anonimo_retorna_401(self, plano_gratuito, valid_data):
        client = APIClient()
        url = reverse("pedido-create-gratuito")
        response = client.post(url, valid_data, format="json")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
