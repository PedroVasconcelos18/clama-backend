"""
Tests do `GET /api/customer/pedidos/` — listagem de pedidos do user
autenticado (spec lp-user-existence-gate / G2.c parcial).

Críticos:
- Isolamento entre users (claim JWT) — user A NÃO vê pedidos de user B.
- Anônimo → 401.
- Ordenação por `created_at` desc (mais recente primeiro).
- Subset seguro de campos (sem cpf_cnpj, sem ip).
"""

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status as drf_status
from rest_framework.test import APIClient

from clama.orders.models import CanalEntrega, Pedido, PedidoStatus
from clama.plans.tests.factories import PlanFactory

User = get_user_model()


CUSTOMER_PASSWORD = "Senha-Forte-12345!"


@pytest.fixture
def plano(db):
    return PlanFactory(ativo=True, valor_centavos=2000)


@pytest.fixture
def customer_alice(db):
    return User.objects.create_user(
        email="alice@example.com",
        password=CUSTOMER_PASSWORD,
        nome_completo="Alice",
    )


@pytest.fixture
def customer_bob(db):
    return User.objects.create_user(
        email="bob@example.com",
        password=CUSTOMER_PASSWORD,
        nome_completo="Bob",
    )


def _criar_pedido(user, plano, **overrides):
    defaults = dict(
        nome=user.nome_completo or user.email,
        email=user.email,
        telefone="+5511999998888",
        cpf_cnpj="11144477735",
        plano=plano,
        valor_centavos=plano.valor_centavos,
        canal_entrega=CanalEntrega.EMAIL,
        status=PedidoStatus.ENVIADA,
        user=user,
    )
    defaults.update(overrides)
    return Pedido.objects.create(**defaults)


def _auth(client, user):
    client.force_authenticate(user=user)
    return client


@pytest.mark.django_db
class TestCustomerPedidosList:
    def test_anonimo_retorna_401(self, db):
        client = APIClient()
        resp = client.get(reverse("customers:pedidos"))
        assert resp.status_code == drf_status.HTTP_401_UNAUTHORIZED

    def test_autenticado_retorna_apenas_pedidos_proprios(
        self, plano, customer_alice, customer_bob
    ):
        # Alice tem 2 pedidos
        _criar_pedido(customer_alice, plano)
        _criar_pedido(customer_alice, plano)
        # Bob tem 1
        _criar_pedido(customer_bob, plano)

        client = _auth(APIClient(), customer_alice)
        resp = client.get(reverse("customers:pedidos"))
        assert resp.status_code == drf_status.HTTP_200_OK

        # DRF wrap em paginator default ou lista direta? ListAPIView default
        # retorna lista pura quando não há paginator configurado. Verifica:
        body = resp.data
        results = body if isinstance(body, list) else body.get("results", [])

        assert len(results) == 2

    def test_user_sem_pedidos_retorna_lista_vazia(self, customer_alice):
        client = _auth(APIClient(), customer_alice)
        resp = client.get(reverse("customers:pedidos"))
        assert resp.status_code == drf_status.HTTP_200_OK
        body = resp.data
        results = body if isinstance(body, list) else body.get("results", [])
        assert results == []

    def test_pedidos_ordenados_mais_recente_primeiro(
        self, plano, customer_alice
    ):
        from django.utils import timezone
        from datetime import timedelta

        p_antigo = _criar_pedido(customer_alice, plano)
        # Mexe direto no DB pra simular pedido antigo (created_at é auto_now_add)
        Pedido.objects.filter(pk=p_antigo.pk).update(
            created_at=timezone.now() - timedelta(days=10)
        )
        p_recente = _criar_pedido(customer_alice, plano)

        client = _auth(APIClient(), customer_alice)
        resp = client.get(reverse("customers:pedidos"))
        body = resp.data
        results = body if isinstance(body, list) else body.get("results", [])

        assert str(results[0]["id"]) == str(p_recente.id)
        assert str(results[1]["id"]) == str(p_antigo.id)

    def test_payload_sem_pii_redundante(self, plano, customer_alice):
        _criar_pedido(customer_alice, plano)
        client = _auth(APIClient(), customer_alice)
        resp = client.get(reverse("customers:pedidos"))
        body = resp.data
        results = body if isinstance(body, list) else body.get("results", [])
        item = results[0]

        # Campos esperados
        for k in [
            "id", "status", "plano", "valor_reais_str", "valor_centavos",
            "eh_gratuito", "canal_entrega", "created_at", "oracao_gerada",
        ]:
            assert k in item, f"campo {k} ausente"

        # Campos perigosos NÃO devem aparecer
        for k in [
            "cpf_cnpj", "telefone", "consent_ip", "asaas_charge_id",
            "asaas_invoice_url", "device_hash",
        ]:
            assert k not in item, f"campo sensível {k} vazado"

    def test_oracao_gerada_oculta_quando_pedido_nao_enviado(
        self, plano, customer_alice
    ):
        _criar_pedido(
            customer_alice,
            plano,
            status=PedidoStatus.GERANDO_ORACAO,
            oracao_gerada="texto oculto pra status pre-envio",
        )
        client = _auth(APIClient(), customer_alice)
        resp = client.get(reverse("customers:pedidos"))
        body = resp.data
        results = body if isinstance(body, list) else body.get("results", [])
        assert results[0]["oracao_gerada"] is None

    def test_oracao_gerada_visivel_quando_pedido_enviada(
        self, plano, customer_alice
    ):
        _criar_pedido(
            customer_alice,
            plano,
            status=PedidoStatus.ENVIADA,
            oracao_gerada="oração entregue com paz",
        )
        client = _auth(APIClient(), customer_alice)
        resp = client.get(reverse("customers:pedidos"))
        body = resp.data
        results = body if isinstance(body, list) else body.get("results", [])
        assert results[0]["oracao_gerada"] == "oração entregue com paz"

    def test_force_change_password_nao_bloqueia_listagem(
        self, plano, customer_alice
    ):
        """`/pedidos/` é read-only, segue acessível com force_change_password=True."""
        customer_alice.force_change_password = True
        customer_alice.save(update_fields=["force_change_password"])
        _criar_pedido(customer_alice, plano)

        client = _auth(APIClient(), customer_alice)
        resp = client.get(reverse("customers:pedidos"))
        assert resp.status_code == drf_status.HTTP_200_OK


@pytest.mark.django_db
class TestCustomerPedidosFiltroData:
    """Filtros `?from=YYYY-MM-DD&to=YYYY-MM-DD`."""

    @pytest.fixture
    def pedidos_em_datas(self, plano, customer_alice):
        """Cria 3 pedidos em datas distintas (10, 20, 30 dias atrás)."""
        from django.utils import timezone
        from datetime import timedelta

        agora = timezone.now()
        pedidos = []
        for dias in (30, 20, 10):
            p = _criar_pedido(customer_alice, plano)
            Pedido.objects.filter(pk=p.pk).update(
                created_at=agora - timedelta(days=dias)
            )
            p.refresh_from_db()
            pedidos.append(p)
        return pedidos

    def _results(self, response):
        body = response.data
        return body if isinstance(body, list) else body.get("results", [])

    def test_filtro_from_inclui_data_limite(
        self, pedidos_em_datas, customer_alice
    ):
        from django.utils import timezone
        from datetime import timedelta

        # `from` = 15 dias atrás → deve incluir o de 10 dias, excluir os
        # de 20 e 30 dias.
        from_date = (timezone.now() - timedelta(days=15)).date().isoformat()
        client = _auth(APIClient(), customer_alice)
        resp = client.get(
            reverse("customers:pedidos") + f"?from={from_date}"
        )
        assert resp.status_code == drf_status.HTTP_200_OK
        results = self._results(resp)
        assert len(results) == 1

    def test_filtro_to_inclui_data_limite(
        self, pedidos_em_datas, customer_alice
    ):
        from django.utils import timezone
        from datetime import timedelta

        # `to` = 15 dias atrás → deve incluir os de 20 e 30, excluir o de 10.
        to_date = (timezone.now() - timedelta(days=15)).date().isoformat()
        client = _auth(APIClient(), customer_alice)
        resp = client.get(
            reverse("customers:pedidos") + f"?to={to_date}"
        )
        assert resp.status_code == drf_status.HTTP_200_OK
        results = self._results(resp)
        assert len(results) == 2

    def test_filtro_from_e_to_combinados(
        self, pedidos_em_datas, customer_alice
    ):
        from django.utils import timezone
        from datetime import timedelta

        agora = timezone.now()
        from_date = (agora - timedelta(days=25)).date().isoformat()
        to_date = (agora - timedelta(days=15)).date().isoformat()
        client = _auth(APIClient(), customer_alice)
        resp = client.get(
            reverse("customers:pedidos") + f"?from={from_date}&to={to_date}"
        )
        results = self._results(resp)
        assert len(results) == 1  # apenas o de 20 dias

    def test_filtro_data_invalida_ignora_silenciosamente(
        self, pedidos_em_datas, customer_alice
    ):
        """Data malformada não quebra a request — UX prefere ignorar."""
        client = _auth(APIClient(), customer_alice)
        resp = client.get(
            reverse("customers:pedidos") + "?from=nao-eh-data&to=outra-coisa"
        )
        assert resp.status_code == drf_status.HTTP_200_OK
        results = self._results(resp)
        assert len(results) == 3  # todos

    def test_filtro_nao_afeta_isolamento_entre_users(
        self, plano, customer_alice, customer_bob
    ):
        """Mesmo com filtro, user nunca vê pedidos de outro."""
        _criar_pedido(customer_alice, plano)
        _criar_pedido(customer_bob, plano)

        client = _auth(APIClient(), customer_alice)
        # Filtro pegando "qualquer pedido criado": Bob não deve aparecer.
        resp = client.get(reverse("customers:pedidos") + "?from=2020-01-01")
        results = self._results(resp)
        assert len(results) == 1
