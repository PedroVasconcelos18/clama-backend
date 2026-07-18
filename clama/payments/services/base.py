"""Contrato agnóstico de gateway de pagamento (port) e seus tipos de domínio."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from rest_framework.request import Request


class StatusPagamento(StrEnum):
    """Estado de domínio de um pagamento, mapeado a partir do status cru do provider."""

    APROVADO = "aprovado"
    PENDENTE = "pendente"
    RECUSADO = "recusado"


@dataclass(frozen=True)
class CobrancaResult:
    """
    Resultado da criação de cobrança: id do provider + dados de pagamento.

    Para Pix (Checkout Transparente), `pix_qr_code` traz o código copia-e-cola
    e `pix_qr_code_base64` a imagem do QR (PNG base64). `checkout_url` guarda a
    `ticket_url` do Mercado Pago (fallback/visualização), podendo ser vazia.
    """

    provider_payment_id: str
    checkout_url: str
    pix_qr_code: str | None = None
    pix_qr_code_base64: str | None = None


@dataclass(frozen=True)
class PagamentoResult:
    """Estado de domínio de um pagamento; `raw_status` guarda o status cru só para logging."""

    status: StatusPagamento
    external_reference: str | None
    raw_status: str | None = None


@dataclass(frozen=True)
class Notificacao:
    """Notificação normalizada de webhook: tipo do evento + id do recurso referenciado."""

    tipo: str
    data_id: str | None


@runtime_checkable
class PaymentProvider(Protocol):
    """Fronteira única com o gateway de pagamento; implementações são intercambiáveis e injetáveis."""

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
        """Cria uma cobrança no gateway e retorna id do provider + URL de checkout."""
        ...

    def buscar_pagamento(self, payment_id: str) -> PagamentoResult:
        """Consulta um pagamento no gateway e devolve seu estado de domínio mapeado."""
        ...

    def validar_assinatura(self, request: Request) -> bool:
        """Valida a assinatura do webhook recebido; True se a requisição é autêntica."""
        ...

    def parse_notification(self, payload: dict, query: dict) -> Notificacao:
        """Normaliza o webhook (body + query) numa Notificacao; `data.id` pode vir do query."""
        ...
