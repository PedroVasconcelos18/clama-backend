"""
Testes de integração do webhook Mercado Pago com o Objetivo 3
(provisionamento de conta + repasse + e-mail de credenciais).

Foca na idempotência do webhook reentrante: reprocessar o mesmo pagamento
não pode criar 2º Repasse, 2ª conta nem 2º e-mail.

⚠️ Requerem DB/app-registry — rodam no ambiente provisionado (não no venv leve).
"""
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIRequestFactory

from clama.instituicoes.models import Repasse
from clama.instituicoes.tests.factories import InstituicaoFactory
from clama.orders.models import PedidoStatus
from clama.orders.tests.factories import PedidoFactory
from clama.payments.api.webhooks import MercadoPagoWebhookView
from clama.payments.services.base import PagamentoResult, StatusPagamento

WEBHOOK_PATH = "/api/webhooks/mercadopago/"


class FakeProvider:
    """Fake do port de pagamento: buscar_pagamento configurável."""

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
    body = body if body is not None else {"id": "notif_1", "type": "payment"}
    factory = APIRequestFactory()
    request = factory.post(f"{WEBHOOK_PATH}?data.id={data_id}", body, format="json")
    view = MercadoPagoWebhookView.as_view(provider=provider)
    return view(request)


def _pagamento(status=StatusPagamento.APROVADO, external_reference=None, raw="approved"):
    return PagamentoResult(
        status=status, external_reference=external_reference, raw_status=raw
    )


@pytest.mark.django_db(transaction=True)
def test_doacao_anonima_gera_repasse_conta_e_email_uma_vez(
    django_capture_on_commit_callbacks,
):
    instituicao = InstituicaoFactory()
    pedido = PedidoFactory(
        status=PedidoStatus.AGUARDANDO_PAGAMENTO,
        user=None,
        instituicao=instituicao,
        valor_centavos=5000,
        email="doador.webhook@exemplo.com",
    )
    provider = FakeProvider(pagamento=_pagamento(external_reference=str(pedido.id)))

    with (
        patch("clama.prayer_generation.tasks.gerar_oracao_task.delay"),
        patch(
            "clama.notifications.tasks.enviar_email_boas_vindas_doador_task.delay"
        ) as mock_boas_vindas,
    ):
        with django_capture_on_commit_callbacks(execute=True):
            response = _post(provider, body={"id": "notif_1", "type": "payment"})

    assert response.status_code == 200
    pedido.refresh_from_db()
    assert pedido.status == PedidoStatus.PAGO

    # 1 Repasse de 20% de 5000 = 1000.
    repasses = Repasse.objects.filter(pedido=pedido)
    assert repasses.count() == 1
    assert repasses.first().valor_centavos == 1000

    # 1 conta criada e vinculada ao pedido.
    user_model = get_user_model()
    assert (
        user_model.objects.filter(email__iexact="doador.webhook@exemplo.com").count()
        == 1
    )
    assert pedido.user_id is not None

    # 1 e-mail de boas-vindas agendado, para o user recém-criado.
    assert mock_boas_vindas.call_count == 1
    assert mock_boas_vindas.call_args[0][0] == str(pedido.user_id)


@pytest.mark.django_db(transaction=True)
def test_webhook_reentrante_nao_duplica_repasse_conta_nem_email(
    django_capture_on_commit_callbacks,
):
    instituicao = InstituicaoFactory()
    pedido = PedidoFactory(
        status=PedidoStatus.AGUARDANDO_PAGAMENTO,
        user=None,
        instituicao=instituicao,
        valor_centavos=5000,
        email="doador.reentrante@exemplo.com",
    )
    provider = FakeProvider(pagamento=_pagamento(external_reference=str(pedido.id)))

    with (
        patch("clama.prayer_generation.tasks.gerar_oracao_task.delay"),
        patch(
            "clama.notifications.tasks.enviar_email_boas_vindas_doador_task.delay"
        ) as mock_boas_vindas,
    ):
        with django_capture_on_commit_callbacks(execute=True):
            _post(provider, body={"id": "notif_1", "type": "payment"})
        # Reentrega da MESMA notificação (linha já PROCESSADO → terminal).
        response2 = _post(provider, body={"id": "notif_1", "type": "payment"})

    assert response2.status_code == 200
    assert response2.data["status"] == "already_processed"

    user_model = get_user_model()
    assert Repasse.objects.filter(pedido=pedido).count() == 1
    assert (
        user_model.objects.filter(
            email__iexact="doador.reentrante@exemplo.com"
        ).count()
        == 1
    )
    assert mock_boas_vindas.call_count == 1  # não reenviou credenciais


@pytest.mark.django_db(transaction=True)
def test_segunda_notificacao_distinta_nao_duplica_conta_nem_email(
    django_capture_on_commit_callbacks,
):
    # 2 notificações com ids distintos para o mesmo pagamento: o state guard
    # (marcar_como_pago 409) barra a 2ª ANTES de provisionar → sem 2ª conta.
    instituicao = InstituicaoFactory()
    pedido = PedidoFactory(
        status=PedidoStatus.AGUARDANDO_PAGAMENTO,
        user=None,
        instituicao=instituicao,
        valor_centavos=5000,
        email="doador.duas@exemplo.com",
    )
    provider = FakeProvider(pagamento=_pagamento(external_reference=str(pedido.id)))

    with (
        patch("clama.prayer_generation.tasks.gerar_oracao_task.delay"),
        patch(
            "clama.notifications.tasks.enviar_email_boas_vindas_doador_task.delay"
        ) as mock_boas_vindas,
    ):
        with django_capture_on_commit_callbacks(execute=True):
            _post(provider, body={"id": "notif_1", "type": "payment"})
        response2 = _post(provider, body={"id": "notif_2", "type": "payment"})

    assert response2.status_code == 200
    assert response2.data["status"] == "already_paid"

    user_model = get_user_model()
    assert Repasse.objects.filter(pedido=pedido).count() == 1
    assert (
        user_model.objects.filter(email__iexact="doador.duas@exemplo.com").count() == 1
    )
    assert mock_boas_vindas.call_count == 1


@pytest.mark.django_db(transaction=True)
def test_doacao_sem_instituicao_provisiona_conta_sem_repasse(
    django_capture_on_commit_callbacks,
):
    pedido = PedidoFactory(
        status=PedidoStatus.AGUARDANDO_PAGAMENTO,
        user=None,
        instituicao=None,
        valor_centavos=5000,
        email="doador.sem.inst@exemplo.com",
    )
    provider = FakeProvider(pagamento=_pagamento(external_reference=str(pedido.id)))

    with (
        patch("clama.prayer_generation.tasks.gerar_oracao_task.delay"),
        patch(
            "clama.notifications.tasks.enviar_email_boas_vindas_doador_task.delay"
        ) as mock_boas_vindas,
    ):
        with django_capture_on_commit_callbacks(execute=True):
            response = _post(provider, body={"id": "notif_1", "type": "payment"})

    assert response.status_code == 200
    # Sem instituição → nenhum repasse; conta e e-mail continuam acontecendo.
    assert Repasse.objects.filter(pedido=pedido).count() == 0
    user_model = get_user_model()
    assert (
        user_model.objects.filter(email__iexact="doador.sem.inst@exemplo.com").count()
        == 1
    )
    assert mock_boas_vindas.call_count == 1
