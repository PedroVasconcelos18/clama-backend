"""
Testes para o endpoint POST /api/pedidos/{id}/checkout/ (Mercado Pago via port).
"""
from unittest.mock import patch

import pytest
from django.core.cache import cache
from django.test import override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from clama.orders.models import PedidoStatus
from clama.orders.tests.factories import PedidoFactory
from clama.payments.exceptions import PaymentProviderError
from clama.payments.services.base import CobrancaResult


class FakeProvider:
    """Fake do port PaymentProvider para os testes do checkout."""

    def __init__(self, result=None, error=None):
        self.result = result or CobrancaResult(
            provider_payment_id="mp_pay_12345",
            checkout_url="https://mp/ticket/mp_pay_12345",
            pix_qr_code="00020126br.gov.bcb.pix6304ABCD",
            pix_qr_code_base64="iVBORw0KGgoAAAANSUhEUg==",
        )
        self.error = error
        self.criar_cobranca_calls = []

    def criar_cobranca(self, **kwargs):
        self.criar_cobranca_calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.result

    def buscar_pagamento(self, payment_id):  # pragma: no cover - não usado no checkout
        raise NotImplementedError

    def validar_assinatura(self, request):  # pragma: no cover
        return True

    def parse_notification(self, payload, query):  # pragma: no cover
        raise NotImplementedError


@pytest.fixture(autouse=True)
def clear_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def pedido_aguardando():
    return PedidoFactory(status=PedidoStatus.AGUARDANDO_PAGAMENTO)


@pytest.fixture
def pedido_pago():
    return PedidoFactory(status=PedidoStatus.PAGO)


@pytest.fixture
def pedido_gerando():
    return PedidoFactory(status=PedidoStatus.GERANDO_ORACAO)


@pytest.fixture
def fake_provider():
    """Injeta um FakeProvider no lugar do MercadoPagoClient default da view."""
    provider = FakeProvider()
    with patch("clama.payments.api.views.MercadoPagoClient", return_value=provider):
        yield provider


def _provider_raising(error):
    """Context manager que injeta um FakeProvider que levanta `error` em criar_cobranca."""
    return patch(
        "clama.payments.api.views.MercadoPagoClient",
        return_value=FakeProvider(error=error),
    )


@pytest.mark.django_db
class TestCheckoutHappyPath:
    def test_checkout_success_returns_200_e_url(self, api_client, pedido_aguardando, fake_provider):
        url = reverse("pedido-checkout", kwargs={"id": pedido_aguardando.id})
        response = api_client.post(url)

        assert response.status_code == status.HTTP_200_OK
        assert response.data["pix_qr_code"] == "00020126br.gov.bcb.pix6304ABCD"
        assert response.data["pix_qr_code_base64"] == "iVBORw0KGgoAAAANSUhEUg=="
        assert response.data["pedido_id"] == str(pedido_aguardando.id)

    def test_checkout_chama_criar_cobranca_com_dados_do_pedido(self, api_client, pedido_aguardando, fake_provider):
        url = reverse("pedido-checkout", kwargs={"id": pedido_aguardando.id})
        api_client.post(url)

        assert len(fake_provider.criar_cobranca_calls) == 1
        call = fake_provider.criar_cobranca_calls[0]
        assert call["valor_centavos"] == pedido_aguardando.valor_centavos
        assert call["cpf_cnpj"] == pedido_aguardando.cpf_cnpj
        assert call["pedido_id"] == str(pedido_aguardando.id)
        assert "Pedido Clama #" in call["descricao"]

    def test_checkout_persiste_provider_fields(self, api_client, pedido_aguardando, fake_provider):
        url = reverse("pedido-checkout", kwargs={"id": pedido_aguardando.id})
        api_client.post(url)

        pedido_aguardando.refresh_from_db()
        assert pedido_aguardando.provider_payment_id == "mp_pay_12345"
        assert pedido_aguardando.pix_qr_code == "00020126br.gov.bcb.pix6304ABCD"
        assert pedido_aguardando.pix_qr_code_base64 == "iVBORw0KGgoAAAANSUhEUg=="

    def test_descricao_sem_pii(self, api_client, pedido_aguardando, fake_provider):
        url = reverse("pedido-checkout", kwargs={"id": pedido_aguardando.id})
        api_client.post(url)

        descricao = fake_provider.criar_cobranca_calls[0]["descricao"]
        assert str(pedido_aguardando.id)[:8] in descricao
        assert pedido_aguardando.nome not in descricao
        assert pedido_aguardando.email not in descricao


@pytest.mark.django_db
class TestCheckoutErrors:
    def test_pedido_not_found_returns_404(self, api_client, fake_provider):
        url = reverse("pedido-checkout", kwargs={"id": "00000000-0000-0000-0000-000000000000"})
        response = api_client.post(url)
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert response.data["error"]["code"] == "not_found"

    def test_pedido_pago_returns_409(self, api_client, pedido_pago, fake_provider):
        url = reverse("pedido-checkout", kwargs={"id": pedido_pago.id})
        response = api_client.post(url)
        assert response.status_code == status.HTTP_409_CONFLICT
        assert response.data["error"]["code"] == "pedido_ja_pago"

    def test_pedido_gerando_returns_409(self, api_client, pedido_gerando, fake_provider):
        url = reverse("pedido-checkout", kwargs={"id": pedido_gerando.id})
        response = api_client.post(url)
        assert response.status_code == status.HTTP_409_CONFLICT

    def test_pedido_sem_cpf_returns_422_sem_chamar_provider(self, api_client, fake_provider):
        pedido = PedidoFactory(status=PedidoStatus.AGUARDANDO_PAGAMENTO, cpf_cnpj="")
        url = reverse("pedido-checkout", kwargs={"id": pedido.id})
        response = api_client.post(url)

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        assert response.data["error"]["code"] == "cpf_cnpj_obrigatorio"
        assert fake_provider.criar_cobranca_calls == []

    @override_settings(MERCADOPAGO_MIN_VALOR_CENTAVOS=500)
    def test_valor_abaixo_minimo_returns_422(self, api_client, fake_provider):
        pedido = PedidoFactory(status=PedidoStatus.AGUARDANDO_PAGAMENTO, valor_centavos=199)
        url = reverse("pedido-checkout", kwargs={"id": pedido.id})
        response = api_client.post(url)

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        assert response.data["error"]["code"] == "valor_abaixo_do_minimo"
        assert fake_provider.criar_cobranca_calls == []

    def test_mp_4xx_user_side_usa_pastoral_ptbr_nao_texto_cru(self, api_client, pedido_aguardando):
        # O MP manda mensagem técnica em inglês — a Juliana NUNCA a vê; recebe a pastoral pt-BR.
        error = PaymentProviderError(
            message="rejected",
            upstream_status=400,
            upstream_body={"cause": [{"description": "The amount is invalid"}]},
        )
        with _provider_raising(error), patch(
            "clama.payments.api.views.sentry_sdk.capture_message"
        ) as mock_sentry:
            url = reverse("pedido-checkout", kwargs={"id": pedido_aguardando.id})
            response = api_client.post(url)

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        msg = response.data["error"]["pastoral_message"]
        assert "The amount is invalid" not in msg  # texto cru do MP não vaza
        assert "soluço" in msg  # pastoral pt-BR (fallback da exceção)
        mock_sentry.assert_not_called()

    def test_mp_4xx_sem_cause_nem_message_usa_fallback_pastoral(self, api_client, pedido_aguardando):
        # Corpo 4xx sem cause[].description nem message → fallback pastoral da exceção.
        error = PaymentProviderError(message="rejected", upstream_status=422, upstream_body={})
        with _provider_raising(error), patch(
            "clama.payments.api.views.sentry_sdk.capture_message"
        ) as mock_sentry:
            url = reverse("pedido-checkout", kwargs={"id": pedido_aguardando.id})
            response = api_client.post(url)

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        assert "soluço" in response.data["error"]["pastoral_message"]
        mock_sentry.assert_not_called()

    def test_mp_4xx_admin_side_esconde_detalhe_e_alerta_sentry(self, api_client, pedido_aguardando):
        error = PaymentProviderError(
            message="unauthorized",
            upstream_status=401,
            upstream_body={"message": "invalid access token", "cause": []},
        )
        with _provider_raising(error), patch(
            "clama.payments.api.views.sentry_sdk.capture_message"
        ) as mock_sentry:
            url = reverse("pedido-checkout", kwargs={"id": pedido_aguardando.id})
            response = api_client.post(url)

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        msg = response.data["error"]["pastoral_message"]
        assert "token" not in msg.lower()
        assert "soluço" in msg or "olhando" in msg
        mock_sentry.assert_called_once()

    def test_mp_5xx_returns_503(self, api_client, pedido_aguardando):
        error = PaymentProviderError(message="unavailable", upstream_status=None)
        with _provider_raising(error):
            url = reverse("pedido-checkout", kwargs={"id": pedido_aguardando.id})
            response = api_client.post(url)

        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE

    def test_erro_nao_altera_status_do_pedido(self, api_client, pedido_aguardando):
        original_status = pedido_aguardando.status
        error = PaymentProviderError(message="unavailable", upstream_status=None)
        with _provider_raising(error):
            url = reverse("pedido-checkout", kwargs={"id": pedido_aguardando.id})
            api_client.post(url)

        pedido_aguardando.refresh_from_db()
        assert pedido_aguardando.status == original_status


@pytest.mark.django_db(transaction=True)
class TestCheckoutIdempotency:
    def test_reusa_cobranca_existente_sem_chamar_provider(self, api_client, fake_provider):
        pedido = PedidoFactory(
            status=PedidoStatus.AGUARDANDO_PAGAMENTO,
            provider_payment_id="mp_pay_existing",
            pix_qr_code="00020126existing6304FFFF",
            pix_qr_code_base64="ZXhpc3Rpbmc=",
        )
        url = reverse("pedido-checkout", kwargs={"id": pedido.id})
        response = api_client.post(url)

        assert response.status_code == status.HTTP_200_OK
        assert response.data["pix_qr_code"] == "00020126existing6304FFFF"
        assert fake_provider.criar_cobranca_calls == []

    def test_estado_parcial_nao_dispara_reuso(self, api_client, fake_provider):
        pedido = PedidoFactory(
            status=PedidoStatus.AGUARDANDO_PAGAMENTO,
            provider_payment_id="pref_existing",
            provider_checkout_url=None,
        )
        url = reverse("pedido-checkout", kwargs={"id": pedido.id})
        api_client.post(url)

        assert len(fake_provider.criar_cobranca_calls) == 1
