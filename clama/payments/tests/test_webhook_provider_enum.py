"""Testes do enum WebhookProvider após adicionar MERCADO_PAGO (MP.3)."""

from clama.payments.models import WebhookProvider


def test_mercado_pago_provider_existe_com_valor_e_label():
    assert WebhookProvider.MERCADO_PAGO == "MERCADO_PAGO"
    assert WebhookProvider.MERCADO_PAGO.label == "Mercado Pago"


def test_providers_anteriores_permanecem():
    assert WebhookProvider.ASAAS == "ASAAS"
    assert WebhookProvider.ZAPI == "ZAPI"
    assert set(WebhookProvider.values) == {"ASAAS", "ZAPI", "MERCADO_PAGO"}
