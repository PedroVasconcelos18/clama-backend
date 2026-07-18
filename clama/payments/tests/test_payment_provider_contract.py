"""Testes de contrato do port PaymentProvider e da exceção PaymentProviderError."""

from clama.payments.exceptions import PaymentProviderError
from clama.payments.services.base import (
    CobrancaResult,
    Notificacao,
    PagamentoResult,
    PaymentProvider,
    StatusPagamento,
)


class InMemoryPaymentProvider:
    """Fake em memória que satisfaz o Protocol PaymentProvider, para testes de injeção."""

    def __init__(self) -> None:
        self.cobrancas: dict[str, int] = {}

    def criar_cobranca(
        self,
        *,
        nome: str,
        email: str,
        cpf_cnpj: str | None,
        valor_centavos: int,
        descricao: str,
        pedido_id: str,
    ) -> CobrancaResult:
        payment_id = f"pay_{pedido_id}"
        self.cobrancas[payment_id] = valor_centavos
        return CobrancaResult(
            provider_payment_id=payment_id,
            checkout_url=f"https://fake.gateway/checkout/{payment_id}",
        )

    def buscar_pagamento(self, payment_id: str) -> PagamentoResult:
        return PagamentoResult(
            status=StatusPagamento.APROVADO,
            external_reference=payment_id.removeprefix("pay_"),
            raw_status="approved",
        )

    def validar_assinatura(self, request) -> bool:
        return True

    def parse_notification(self, payload: dict, query: dict) -> Notificacao:
        return Notificacao(tipo=payload.get("type", ""), data_id=query.get("data.id"))


def _processar_checkout(provider: PaymentProvider, pedido_id: str) -> CobrancaResult:
    """Consumidor que aceita qualquer PaymentProvider — exercita a injeção do port."""
    return provider.criar_cobranca(
        nome="Juliana",
        email="juliana@example.com",
        cpf_cnpj=None,
        valor_centavos=5000,
        descricao="Oferta",
        pedido_id=pedido_id,
    )


def test_fake_provider_satisfaz_o_protocol_em_runtime():
    provider = InMemoryPaymentProvider()
    assert isinstance(provider, PaymentProvider)


def test_port_e_injetavel_onde_paymentprovider_e_esperado():
    provider = InMemoryPaymentProvider()
    result = _processar_checkout(provider, "abc")
    assert isinstance(result, CobrancaResult)
    assert result.provider_payment_id == "pay_abc"
    assert result.checkout_url.endswith("pay_abc")


def test_buscar_pagamento_retorna_status_de_dominio_e_raw_status():
    provider = InMemoryPaymentProvider()
    pagamento = provider.buscar_pagamento("pay_abc")
    assert pagamento.status is StatusPagamento.APROVADO
    assert pagamento.external_reference == "abc"
    assert pagamento.raw_status == "approved"


def test_parse_notification_le_data_id_do_query_param():
    provider = InMemoryPaymentProvider()
    notif = provider.parse_notification({"type": "payment"}, {"data.id": "12345"})
    assert notif.tipo == "payment"
    assert notif.data_id == "12345"


def test_status_pagamento_tem_os_tres_estados_de_dominio():
    assert {s.value for s in StatusPagamento} == {"aprovado", "pendente", "recusado"}


def test_payment_provider_error_tem_pastoral_message_default_ptbr():
    err = PaymentProviderError()
    assert err.code == "payment_provider_error"
    assert err.pastoral_message
    assert "pagamento" in err.pastoral_message.lower()
    assert err.upstream_status is None
    assert err.upstream_body is None


def test_payment_provider_error_preserva_upstream_status_e_body():
    err = PaymentProviderError(
        message="cobrança recusada",
        upstream_status=422,
        upstream_body={"erro": "cpf_cnpj invalido"},
    )
    assert err.message == "cobrança recusada"
    assert err.upstream_status == 422
    assert err.upstream_body == {"erro": "cpf_cnpj invalido"}


def test_payment_provider_error_repassa_extra_para_o_handler():
    err = PaymentProviderError(
        pastoral_message="Não conseguimos finalizar o pagamento.",
        extra={"redirect": "/cancelado"},
    )
    assert err.extra == {"redirect": "/cancelado"}
