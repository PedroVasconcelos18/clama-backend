"""
Testes do endpoint POST /api/doacoes/ (doação paga SEM conta, LP anônima).

Cobre a I/O Matrix da doação anônima:
- Turnstile mock (secret vazio em teste) → cria Pedido `user=None`,
  AGUARDANDO_PAGAMENTO.
- valor < 100 → 400.
- consent ausente → 400.
- Turnstile ausente / inválido → 400 (nada persistido).
- e-mail descartável / CPF inválido → 400.
- instituição opcional (com e sem).

Espelha o padrão de mock do Turnstile dos testes do freemium
(`clama/freemium/tests/`): o `TurnstileClient.validate` é patchado no
namespace da view de orders.
"""

from unittest.mock import patch

import pytest
from django.core.cache import cache
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from clama.instituicoes.tests.factories import InstituicaoFactory
from clama.orders.models import CanalEntrega, Pedido, PedidoStatus
from clama.plans.tests.factories import PlanFactory

CPF_VALIDO = "11144477735"


@pytest.fixture(autouse=True)
def clear_cache():
    """Limpa o cache antes/depois de cada teste (isola rate limiting)."""
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def api_client():
    """Client anônimo — o endpoint é AllowAny."""
    return APIClient()


@pytest.fixture
def plano_ativo(db):
    """Plano visível e ativo — a derivação de plano por valor o seleciona."""
    return PlanFactory(ativo=True, visivel=True, valor_centavos=1000)


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
        "cpf_cnpj": CPF_VALIDO,
        "valor_centavos": 5000,
        "consent_aceito": True,
        "turnstile_token": "qualquer-token-nao-vazio",
        "device_hash": "abcdef1234567890",
    }


@pytest.fixture
def turnstile_invalido():
    """Força `TurnstileClient.validate` (na view de orders) a retornar False."""
    with patch(
        "clama.orders.api.views.TurnstileClient.validate",
        return_value=False,
    ) as mocked:
        yield mocked


@pytest.mark.django_db
class TestDoacaoAnonimaHappy:
    def test_cria_pedido_anonimo_aguardando_pagamento(
        self, api_client, plano_ativo, valid_data
    ):
        url = reverse("doacao-anonima-create")
        response = api_client.post(url, valid_data, format="json")

        assert response.status_code == status.HTTP_201_CREATED, response.data
        assert "id" in response.data
        assert response.data["status"] == PedidoStatus.AGUARDANDO_PAGAMENTO

        pedido = Pedido.objects.get(id=response.data["id"])
        assert pedido.user is None
        assert pedido.status == PedidoStatus.AGUARDANDO_PAGAMENTO
        assert pedido.valor_centavos == 5000
        assert pedido.eh_gratuito is False
        # Um plano é derivado do valor (inferência/fallback) — não necessariamente
        # o `plano_ativo` do fixture, já que o valor (5000) não casa com ele (1000).
        assert pedido.plano_id is not None
        # device_hash persistido (instrumentação anti-abuso).
        assert pedido.device_hash == "abcdef1234567890"
        # consent capturado.
        assert pedido.consent_aceito is True
        assert pedido.consent_aceito_at is not None

    def test_nao_exige_autenticacao(self, api_client, plano_ativo, valid_data):
        """Endpoint AllowAny — anônimo cria a doação normalmente."""
        url = reverse("doacao-anonima-create")
        response = api_client.post(url, valid_data, format="json")
        assert response.status_code == status.HTTP_201_CREATED


@pytest.mark.django_db
class TestDoacaoAnonimaValidacao:
    def test_valor_abaixo_de_100_retorna_400(self, api_client, plano_ativo, valid_data):
        valid_data["valor_centavos"] = 50
        url = reverse("doacao-anonima-create")
        response = api_client.post(url, valid_data, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert not Pedido.objects.exists()

    def test_consent_ausente_retorna_400(self, api_client, plano_ativo, valid_data):
        valid_data["consent_aceito"] = False
        url = reverse("doacao-anonima-create")
        response = api_client.post(url, valid_data, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert not Pedido.objects.exists()

    def test_cpf_invalido_retorna_400(self, api_client, plano_ativo, valid_data):
        valid_data["cpf_cnpj"] = "11111111111"
        url = reverse("doacao-anonima-create")
        response = api_client.post(url, valid_data, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert not Pedido.objects.exists()

    def test_email_descartavel_retorna_400(self, api_client, plano_ativo, valid_data):
        valid_data["email"] = "user@mailinator.com"
        url = reverse("doacao-anonima-create")
        response = api_client.post(url, valid_data, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data["error"]["code"] == "email_descartavel"
        assert not Pedido.objects.exists()


@pytest.mark.django_db
class TestDoacaoAnonimaTurnstile:
    def test_turnstile_invalido_retorna_400(
        self, api_client, plano_ativo, valid_data, turnstile_invalido
    ):
        url = reverse("doacao-anonima-create")
        response = api_client.post(url, valid_data, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data["error"]["code"] == "captcha_invalido"
        # Nada persistido — Turnstile é validado antes de qualquer escrita.
        assert not Pedido.objects.exists()

    def test_turnstile_ausente_retorna_400(self, api_client, plano_ativo, valid_data):
        valid_data.pop("turnstile_token")
        url = reverse("doacao-anonima-create")
        response = api_client.post(url, valid_data, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert not Pedido.objects.exists()

    def test_turnstile_vazio_retorna_400(self, api_client, plano_ativo, valid_data):
        valid_data["turnstile_token"] = ""
        url = reverse("doacao-anonima-create")
        response = api_client.post(url, valid_data, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert not Pedido.objects.exists()


@pytest.mark.django_db
class TestDoacaoAnonimaInstituicao:
    def test_com_instituicao_ativa(self, api_client, plano_ativo, valid_data):
        instituicao = InstituicaoFactory(ativo=True)
        valid_data["instituicao"] = str(instituicao.id)
        url = reverse("doacao-anonima-create")
        response = api_client.post(url, valid_data, format="json")

        assert response.status_code == status.HTTP_201_CREATED
        pedido = Pedido.objects.get(id=response.data["id"])
        assert pedido.instituicao_id == instituicao.id

    def test_sem_instituicao(self, api_client, plano_ativo, valid_data):
        url = reverse("doacao-anonima-create")
        response = api_client.post(url, valid_data, format="json")

        assert response.status_code == status.HTTP_201_CREATED
        pedido = Pedido.objects.get(id=response.data["id"])
        assert pedido.instituicao_id is None

    def test_instituicao_inativa_retorna_400(self, api_client, plano_ativo, valid_data):
        """Instituição inativa não está no queryset (ativo=True) → 400."""
        instituicao = InstituicaoFactory(ativo=False)
        valid_data["instituicao"] = str(instituicao.id)
        url = reverse("doacao-anonima-create")
        response = api_client.post(url, valid_data, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert not Pedido.objects.exists()
