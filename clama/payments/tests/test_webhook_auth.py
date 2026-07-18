"""Testes do MercadoPagoWebhookAuthMiddleware e da função canônica de assinatura (MP.5/AD-3)."""

import hashlib
import hmac

from django.http import JsonResponse
from django.test import RequestFactory, override_settings

from clama.payments.middleware import MercadoPagoWebhookAuthMiddleware
from clama.payments.services.mercadopago_client import verificar_assinatura_webhook

SECRET = "segredo-teste"
PATH = "/api/webhooks/mercadopago/"


def _assinar(data_id: str, request_id: str, ts: str, secret: str = SECRET) -> str:
    manifest = f"id:{data_id.lower()};request-id:{request_id};ts:{ts};"
    return hmac.new(secret.encode(), manifest.encode(), hashlib.sha256).hexdigest()


def _signed_request(rf, *, data_id="12345", request_id="req-1", ts="1700000000", v1=None, body=b""):
    if v1 is None:
        v1 = _assinar(data_id, request_id, ts)
    return rf.post(
        f"{PATH}?data.id={data_id}",
        data=body,
        content_type="application/json",
        HTTP_X_SIGNATURE=f"ts={ts},v1={v1}",
        HTTP_X_REQUEST_ID=request_id,
    )


# ---------- função canônica ----------


@override_settings(MERCADOPAGO_WEBHOOK_SECRET=SECRET)
def test_verificar_assinatura_valida():
    assert verificar_assinatura_webhook(_signed_request(RequestFactory())) is True


@override_settings(MERCADOPAGO_WEBHOOK_SECRET=SECRET)
def test_verificar_assinatura_v1_adulterado():
    req = _signed_request(RequestFactory(), v1="deadbeef")
    assert verificar_assinatura_webhook(req) is False


@override_settings(MERCADOPAGO_WEBHOOK_SECRET=SECRET)
def test_verificar_assinatura_header_ausente():
    req = RequestFactory().post(f"{PATH}?data.id=123")
    assert verificar_assinatura_webhook(req) is False


@override_settings(MERCADOPAGO_WEBHOOK_SECRET="")
def test_verificar_assinatura_sem_secret():
    assert verificar_assinatura_webhook(_signed_request(RequestFactory())) is False


# ---------- middleware ----------


class _Sentinel:
    """get_response que registra a request recebida e devolve um marcador."""

    def __init__(self):
        self.called_with = None

    def __call__(self, request):
        self.called_with = request
        return "PASSED_THROUGH"


def test_middleware_fast_path_rota_nao_protegida():
    sentinel = _Sentinel()
    mw = MercadoPagoWebhookAuthMiddleware(sentinel)
    req = RequestFactory().get("/api/pedidos/")
    result = mw(req)
    assert result == "PASSED_THROUGH"
    assert sentinel.called_with is req


@override_settings(MERCADOPAGO_WEBHOOK_SECRET=SECRET)
def test_middleware_assinatura_valida_passa_para_view():
    sentinel = _Sentinel()
    mw = MercadoPagoWebhookAuthMiddleware(sentinel)
    req = _signed_request(RequestFactory())
    result = mw(req)
    assert result == "PASSED_THROUGH"
    assert sentinel.called_with is req


@override_settings(MERCADOPAGO_WEBHOOK_SECRET=SECRET)
def test_middleware_assinatura_invalida_retorna_401_sem_chamar_view():
    sentinel = _Sentinel()
    mw = MercadoPagoWebhookAuthMiddleware(sentinel)
    req = _signed_request(RequestFactory(), v1="deadbeef")
    result = mw(req)
    assert isinstance(result, JsonResponse)
    assert result.status_code == 401
    assert sentinel.called_with is None


@override_settings(MERCADOPAGO_WEBHOOK_SECRET=SECRET)
def test_middleware_nao_consome_o_body_da_request():
    # O middleware não pode ler request.body — a view (DRF) precisa dele intacto.
    sentinel = _Sentinel()
    mw = MercadoPagoWebhookAuthMiddleware(sentinel)
    body = b'{"type": "payment", "id": 999}'
    req = _signed_request(RequestFactory(), body=body)
    mw(req)
    assert sentinel.called_with.body == body
