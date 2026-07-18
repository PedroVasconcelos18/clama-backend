"""Testes dos campos de pagamento agnósticos de provider no Pedido (MP.3)."""

import pytest

from clama.orders.tests.factories import PedidoFactory


@pytest.mark.django_db
def test_pedido_nasce_com_provider_fields_nulos():
    # Sem backfill de asaas_* — os campos provider_* nascem nulos (AC1).
    pedido = PedidoFactory()
    assert pedido.provider_payment_id is None
    assert pedido.provider_checkout_url is None


@pytest.mark.django_db
def test_pedido_aceita_provider_fields_preenchidos():
    pedido = PedidoFactory(
        provider_payment_id="pref_123",
        provider_checkout_url="https://mp/checkout/pref_123",
    )
    pedido.refresh_from_db()
    assert pedido.provider_payment_id == "pref_123"
    assert pedido.provider_checkout_url == "https://mp/checkout/pref_123"
