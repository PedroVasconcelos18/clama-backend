"""
Testes da MercadoPagoWebhookView (AD-2/AD-4/AD-5).

⚠️ Requerem DB/app-registry — rodar no ambiente provisionado (não rodam no venv leve).
"""
from unittest.mock import patch

import pytest
from rest_framework.test import APIRequestFactory

from clama.orders.models import PedidoStatus
from clama.orders.tests.factories import PedidoFactory
from clama.payments.api.webhooks import MercadoPagoWebhookView
from clama.payments.exceptions import PaymentProviderError
from clama.payments.models import WebhookEvento, WebhookEventoStatus, WebhookProvider
from clama.payments.services.base import PagamentoResult, StatusPagamento

WEBHOOK_PATH = "/api/webhooks/mercadopago/"


class FakeProvider:
    """Fake do port para a webhook view: buscar_pagamento configurável."""

    def __init__(self, pagamento=None, error=None):
        self.pagamento = pagamento
        self.error = error
        self.buscar_calls = []

    def buscar_pagamento(self, payment_id):
        self.buscar_calls.append(payment_id)
        if self.error is not None:
            raise self.error
        return self.pagamento


def _post(provider, *, data_id="pay_1", body=None):
    """Chama a view diretamente (bypassa o middleware) com o provider injetado."""
    body = body if body is not None else {"id": "notif_1", "type": "payment"}
    factory = APIRequestFactory()
    request = factory.post(f"{WEBHOOK_PATH}?data.id={data_id}", body, format="json")
    view = MercadoPagoWebhookView.as_view(provider=provider)
    return view(request)


def _pagamento(status=StatusPagamento.APROVADO, external_reference=None, raw="approved"):
    return PagamentoResult(status=status, external_reference=external_reference, raw_status=raw)


@pytest.mark.django_db(transaction=True)
def test_a_notificacao_aprovada_provisiona_uma_vez(django_capture_on_commit_callbacks):
    pedido = PedidoFactory(status=PedidoStatus.AGUARDANDO_PAGAMENTO)
    provider = FakeProvider(pagamento=_pagamento(external_reference=str(pedido.id)))

    with patch("clama.prayer_generation.tasks.gerar_oracao_task.delay") as mock_delay:
        with django_capture_on_commit_callbacks(execute=True):
            response = _post(provider, body={"id": "notif_1", "type": "payment"})

    assert response.status_code == 200
    pedido.refresh_from_db()
    assert pedido.status == PedidoStatus.PAGO
    mock_delay.assert_called_once_with(str(pedido.id))
    evento = WebhookEvento.objects.get(external_event_id="notif_1")
    assert evento.status == WebhookEventoStatus.PROCESSADO
    assert evento.provider == WebhookProvider.MERCADO_PAGO


@pytest.mark.django_db(transaction=True)
def test_b_notificacao_repetida_terminal_nao_reprocessa(django_capture_on_commit_callbacks):
    pedido = PedidoFactory(status=PedidoStatus.AGUARDANDO_PAGAMENTO)
    provider = FakeProvider(pagamento=_pagamento(external_reference=str(pedido.id)))

    with patch("clama.prayer_generation.tasks.gerar_oracao_task.delay") as mock_delay:
        with django_capture_on_commit_callbacks(execute=True):
            _post(provider, body={"id": "notif_1", "type": "payment"})
        # Segunda entrega da MESMA notificação (linha já PROCESSADO → terminal)
        response2 = _post(provider, body={"id": "notif_1", "type": "payment"})

    assert response2.status_code == 200
    assert response2.data["status"] == "already_processed"
    assert mock_delay.call_count == 1  # não disparou de novo


@pytest.mark.django_db(transaction=True)
def test_c_duas_notificacoes_mesmo_pagamento_provisiona_uma_vez(django_capture_on_commit_callbacks):
    # 2 notificações com ids distintos para o mesmo pagamento → state guard garante 1 provisão.
    pedido = PedidoFactory(status=PedidoStatus.AGUARDANDO_PAGAMENTO)
    provider = FakeProvider(pagamento=_pagamento(external_reference=str(pedido.id)))

    with patch("clama.prayer_generation.tasks.gerar_oracao_task.delay") as mock_delay:
        with django_capture_on_commit_callbacks(execute=True):
            _post(provider, body={"id": "notif_1", "type": "payment"})
        response2 = _post(provider, body={"id": "notif_2", "type": "payment"})

    assert response2.status_code == 200  # idempotente, nunca 500
    assert response2.data["status"] == "already_paid"
    assert mock_delay.call_count == 1


@pytest.mark.django_db
def test_d_tipo_nao_payment_ignora_sem_fetch():
    provider = FakeProvider(pagamento=_pagamento())
    response = _post(provider, body={"id": "notif_mo", "type": "merchant_order"})

    assert response.status_code == 200
    assert response.data["status"] == "ignored"
    assert provider.buscar_calls == []  # sem fetch


@pytest.mark.django_db
def test_e_status_pending_ignora():
    pedido = PedidoFactory(status=PedidoStatus.AGUARDANDO_PAGAMENTO)
    provider = FakeProvider(
        pagamento=_pagamento(status=StatusPagamento.PENDENTE, external_reference=str(pedido.id), raw="pending")
    )
    response = _post(provider, body={"id": "notif_p", "type": "payment"})

    assert response.status_code == 200
    assert response.data["status"] == "ignored"
    pedido.refresh_from_db()
    assert pedido.status == PedidoStatus.AGUARDANDO_PAGAMENTO


@pytest.mark.django_db
def test_f_erro_transiente_deixa_linha_reprocessavel_e_500():
    provider = FakeProvider(error=PaymentProviderError(message="boom", upstream_status=503))
    response = _post(provider, body={"id": "notif_err", "type": "payment"})

    assert response.status_code == 500
    evento = WebhookEvento.objects.get(external_event_id="notif_err")
    # ERRO é NÃO-terminal → o MP reenvia e a notificação é reprocessada.
    assert evento.status == WebhookEventoStatus.ERRO
    assert evento.status not in {WebhookEventoStatus.PROCESSADO, WebhookEventoStatus.IGNORADO}


@pytest.mark.django_db
def test_g_pedido_inexistente_ignora_200():
    provider = FakeProvider(pagamento=_pagamento(external_reference="00000000-0000-0000-0000-000000000000"))
    response = _post(provider, body={"id": "notif_orphan", "type": "payment"})

    assert response.status_code == 200
    assert response.data["status"] == "ignored"


@pytest.mark.django_db
def test_external_reference_nao_uuid_ignora_200_sem_500():
    # UUIDField levanta ValidationError (não ValueError) — deve ser tratado como ignorado, não 500.
    provider = FakeProvider(pagamento=_pagamento(external_reference="nao-e-uuid"))
    response = _post(provider, body={"id": "notif_bad_ref", "type": "payment"})

    assert response.status_code == 200
    assert response.data["status"] == "ignored"


@pytest.mark.django_db
def test_fetch_4xx_ignora_200_sem_loop_de_retry():
    # 4xx no fetch (token errado / pagamento inexistente) não é transiente → 200 ignorado,
    # não 500 (que faria o MP retentar pra sempre).
    provider = FakeProvider(error=PaymentProviderError(message="unauthorized", upstream_status=401))
    response = _post(provider, body={"id": "notif_4xx", "type": "payment"})

    assert response.status_code == 200
    assert response.data["status"] == "ignored"
    evento = WebhookEvento.objects.get(external_event_id="notif_4xx")
    assert evento.status == WebhookEventoStatus.IGNORADO


@pytest.mark.django_db
def test_fetch_acontece_antes_de_qualquer_lock():
    # AD-4: buscar_pagamento é chamado (fora do lock) antes da provisão.
    pedido = PedidoFactory(status=PedidoStatus.AGUARDANDO_PAGAMENTO)
    provider = FakeProvider(pagamento=_pagamento(external_reference=str(pedido.id)))
    with patch("clama.prayer_generation.tasks.gerar_oracao_task.delay"):
        _post(provider, body={"id": "notif_1", "type": "payment"})
    assert provider.buscar_calls == ["pay_1"]  # fetch ocorreu, uma vez
