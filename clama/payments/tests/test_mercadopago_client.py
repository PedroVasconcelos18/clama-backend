"""Testes do adapter MercadoPagoClient (SDK sempre injetado/mockado — nunca API real)."""

import hashlib
import hmac

import pytest
import requests
from django.test import RequestFactory, override_settings

from clama.payments.exceptions import PaymentProviderError
from clama.payments.services.base import (
    CobrancaResult,
    Notificacao,
    PagamentoResult,
    PaymentProvider,
    StatusPagamento,
)
from clama.payments.services.mercadopago_client import MercadoPagoClient


class FakeEndpoint:
    """Fake de `sdk.preference()` / `sdk.payment()`; conta chamadas e guarda o payload.

    Se `raises` for passado, cada chamada levanta essa exceção (simula falha de rede).
    """

    def __init__(self, result=None, raises=None):
        self.result = result
        self.raises = raises
        self.calls = 0
        self.last_data = None
        self.last_id = None

    def create(self, data):
        self.calls += 1
        self.last_data = data
        if self.raises is not None:
            raise self.raises
        return self.result

    def get(self, payment_id):
        self.calls += 1
        self.last_id = payment_id
        if self.raises is not None:
            raise self.raises
        return self.result


class FakeSDK:
    """Fake do `mercadopago.SDK` — devolve endpoints fake fixos."""

    def __init__(self, preference=None, payment=None):
        self._preference = preference or FakeEndpoint({"status": 201, "response": {}})
        self._payment = payment or FakeEndpoint({"status": 200, "response": {}})

    def preference(self):
        return self._preference

    def payment(self):
        return self._payment


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    """Zera o backoff do @with_retry para os testes de retry não dormirem."""
    monkeypatch.setattr("clama.core.retry.time.sleep", lambda _s: None)


# ---------- criar_cobranca ----------


@override_settings(
    BACKEND_PUBLIC_URL="https://api.clama.com.br",
    FRONTEND_URL="https://clama.com.br",
)
def test_criar_cobranca_cria_preference_pix_priority_e_retorna_init_point():
    pref = FakeEndpoint(
        {
            "status": 201,
            "response": {"id": "pref_123", "init_point": "https://mp/checkout/pref_123"},
        }
    )
    client = MercadoPagoClient(sdk=FakeSDK(preference=pref))

    result = client.criar_cobranca(
        nome="Juliana",
        email="juliana@example.com",
        cpf_cnpj="12345678909",
        valor_centavos=5000,
        descricao="Oferta Clama",
        pedido_id="abc-123",
    )

    assert isinstance(result, CobrancaResult)
    assert result.provider_payment_id == "pref_123"
    assert result.checkout_url == "https://mp/checkout/pref_123"

    data = pref.last_data
    assert data["external_reference"] == "abc-123"
    assert data["items"][0]["unit_price"] == 50.0
    assert data["items"][0]["currency_id"] == "BRL"
    excluded = {p["id"] for p in data["payment_methods"]["excluded_payment_types"]}
    assert excluded == {"credit_card", "debit_card", "ticket"}
    assert data["notification_url"] == "https://api.clama.com.br/api/webhooks/mercadopago/"
    assert data["back_urls"]["success"] == "https://clama.com.br/confirmacao?pedido_id=abc-123"
    assert data["auto_return"] == "approved"


def test_criar_cobranca_4xx_vira_payment_provider_error_sem_retry():
    pref = FakeEndpoint({"status": 422, "response": {"message": "invalid params"}})
    client = MercadoPagoClient(sdk=FakeSDK(preference=pref))

    with pytest.raises(PaymentProviderError) as exc:
        client.criar_cobranca(
            nome="Juliana",
            email="juliana@example.com",
            cpf_cnpj=None,
            valor_centavos=5000,
            descricao="Oferta",
            pedido_id="abc",
        )

    assert exc.value.upstream_status == 422
    assert exc.value.upstream_body == {"message": "invalid params"}
    assert pref.calls == 1  # 4xx não retenta


def test_criar_cobranca_5xx_retenta_3x_e_vira_payment_provider_error():
    pref = FakeEndpoint({"status": 503, "response": {"message": "service unavailable"}})
    client = MercadoPagoClient(sdk=FakeSDK(preference=pref))

    with pytest.raises(PaymentProviderError) as exc:
        client.criar_cobranca(
            nome="Juliana",
            email="juliana@example.com",
            cpf_cnpj=None,
            valor_centavos=5000,
            descricao="Oferta",
            pedido_id="abc",
        )

    assert exc.value.upstream_status == 503
    assert pref.calls == 3  # esgota as 3 tentativas


# ---------- buscar_pagamento ----------


@pytest.mark.parametrize(
    "mp_status,esperado",
    [
        ("approved", StatusPagamento.APROVADO),
        ("pending", StatusPagamento.PENDENTE),
        ("in_process", StatusPagamento.PENDENTE),
        ("authorized", StatusPagamento.PENDENTE),
        ("rejected", StatusPagamento.RECUSADO),
        ("cancelled", StatusPagamento.RECUSADO),
        ("refunded", StatusPagamento.RECUSADO),
        ("charged_back", StatusPagamento.RECUSADO),
        ("bananas", StatusPagamento.PENDENTE),
    ],
)
def test_buscar_pagamento_mapeia_status_de_dominio(mp_status, esperado):
    pay = FakeEndpoint(
        {
            "status": 200,
            "response": {"status": mp_status, "external_reference": "pedido-1"},
        }
    )
    client = MercadoPagoClient(sdk=FakeSDK(payment=pay))

    result = client.buscar_pagamento("mp_pay_1")

    assert isinstance(result, PagamentoResult)
    assert result.status is esperado
    assert result.external_reference == "pedido-1"
    assert result.raw_status == mp_status
    assert pay.last_id == "mp_pay_1"


def test_buscar_pagamento_5xx_retenta_3x():
    pay = FakeEndpoint({"status": 500, "response": {"message": "boom"}})
    client = MercadoPagoClient(sdk=FakeSDK(payment=pay))

    with pytest.raises(PaymentProviderError):
        client.buscar_pagamento("mp_pay_1")

    assert pay.calls == 3


# ---------- parse_notification ----------


def test_parse_notification_le_type_do_body_e_data_id_do_query():
    client = MercadoPagoClient(sdk=FakeSDK())
    notif = client.parse_notification({"type": "payment"}, {"data.id": "999"})
    assert isinstance(notif, Notificacao)
    assert notif.tipo == "payment"
    assert notif.data_id == "999"


# ---------- validar_assinatura (HMAC canônico — AD-3) ----------


def _assinar(secret: str, data_id: str, request_id: str, ts: str) -> str:
    manifest = f"id:{data_id.lower()};request-id:{request_id};ts:{ts};"
    return hmac.new(secret.encode(), manifest.encode(), hashlib.sha256).hexdigest()


@override_settings(MERCADOPAGO_WEBHOOK_SECRET="segredo-teste")
def test_validar_assinatura_aceita_assinatura_valida():
    v1 = _assinar("segredo-teste", data_id="12345", request_id="req-1", ts="1700000000")
    request = RequestFactory().post(
        "/api/webhooks/mercadopago/?data.id=12345",
        HTTP_X_SIGNATURE=f"ts=1700000000,v1={v1}",
        HTTP_X_REQUEST_ID="req-1",
    )
    client = MercadoPagoClient(sdk=FakeSDK())
    assert client.validar_assinatura(request) is True


@override_settings(MERCADOPAGO_WEBHOOK_SECRET="segredo-teste")
def test_validar_assinatura_rejeita_v1_adulterado():
    request = RequestFactory().post(
        "/api/webhooks/mercadopago/?data.id=12345",
        HTTP_X_SIGNATURE="ts=1700000000,v1=deadbeef",
        HTTP_X_REQUEST_ID="req-1",
    )
    client = MercadoPagoClient(sdk=FakeSDK())
    assert client.validar_assinatura(request) is False


@override_settings(MERCADOPAGO_WEBHOOK_SECRET="")
def test_validar_assinatura_sem_secret_configurado_retorna_false():
    request = RequestFactory().post(
        "/api/webhooks/mercadopago/?data.id=12345",
        HTTP_X_SIGNATURE="ts=1700000000,v1=abc",
        HTTP_X_REQUEST_ID="req-1",
    )
    client = MercadoPagoClient(sdk=FakeSDK())
    assert client.validar_assinatura(request) is False


# ---------- mapeamento isolado ----------


def test_mapear_status_funcao_pura():
    assert MercadoPagoClient._mapear_status("approved") is StatusPagamento.APROVADO
    assert MercadoPagoClient._mapear_status("rejected") is StatusPagamento.RECUSADO
    assert MercadoPagoClient._mapear_status("pending") is StatusPagamento.PENDENTE
    assert MercadoPagoClient._mapear_status(None) is StatusPagamento.PENDENTE


# ---------- fixes do code review ----------


def test_adapter_e_instancia_do_port():
    # AC1: MercadoPagoClient(PaymentProvider) — conformidade explícita com o port.
    assert isinstance(MercadoPagoClient(sdk=FakeSDK()), PaymentProvider)


def test_criar_cobranca_erro_de_rede_vira_payment_provider_error():
    # Erro de rede é retentado 3x pelo @with_retry e convertido em PaymentProviderError (AD-6).
    pref = FakeEndpoint(raises=requests.ConnectionError("boom"))
    client = MercadoPagoClient(sdk=FakeSDK(preference=pref))

    with pytest.raises(PaymentProviderError) as exc:
        client.criar_cobranca(
            nome="Juliana",
            email="juliana@example.com",
            cpf_cnpj=None,
            valor_centavos=5000,
            descricao="Oferta",
            pedido_id="abc",
        )

    assert exc.value.upstream_status is None
    assert pref.calls == 3


def test_criar_cobranca_2xx_sem_id_vira_payment_provider_error():
    pref = FakeEndpoint({"status": 201, "response": {"init_point": "https://mp/x"}})
    client = MercadoPagoClient(sdk=FakeSDK(preference=pref))

    with pytest.raises(PaymentProviderError):
        client.criar_cobranca(
            nome="Juliana",
            email="j@example.com",
            cpf_cnpj=None,
            valor_centavos=5000,
            descricao="Oferta",
            pedido_id="abc",
        )


def test_buscar_pagamento_corpo_2xx_nao_dict_vira_payment_provider_error():
    pay = FakeEndpoint({"status": 200, "response": None})
    client = MercadoPagoClient(sdk=FakeSDK(payment=pay))

    with pytest.raises(PaymentProviderError):
        client.buscar_pagamento("mp_pay_1")


@override_settings(MERCADOPAGO_WEBHOOK_SECRET="segredo-teste")
def test_validar_assinatura_v1_nao_ascii_retorna_false_sem_crashar():
    # v1 com caractere não-ASCII faria hmac.compare_digest levantar TypeError → deve virar False.
    request = RequestFactory().post(
        "/api/webhooks/mercadopago/?data.id=12345",
        HTTP_X_SIGNATURE="ts=1700000000,v1=café",
        HTTP_X_REQUEST_ID="req-1",
    )
    client = MercadoPagoClient(sdk=FakeSDK())
    assert client.validar_assinatura(request) is False
