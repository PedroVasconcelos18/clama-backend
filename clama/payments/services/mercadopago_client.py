"""Adapter do port PaymentProvider para o Mercado Pago (Checkout Pro + pagamentos + assinatura)."""

import hashlib
import hmac
import logging
import time

import requests
from django.conf import settings

from clama.core.retry import get_current_attempt, with_retry
from clama.payments.exceptions import PaymentProviderError
from clama.payments.services.base import (
    CobrancaResult,
    Notificacao,
    PagamentoResult,
    PaymentProvider,
    StatusPagamento,
)

logger = logging.getLogger("clama.payments.mercadopago_client")

_RETRIABLE_STATUS = [500, 502, 503, 504]

# Mapa status cru do Mercado Pago → estado de domínio. Ausente aqui ⇒ PENDENTE.
_STATUS_APROVADO = frozenset({"approved"})
_STATUS_RECUSADO = frozenset({"rejected", "cancelled", "refunded", "charged_back"})


class _TransientMPError(Exception):
    """Erro transiente (5xx) do Mercado Pago; carrega `status_code` para o @with_retry retentar."""

    def __init__(self, status_code: int, body):
        self.status_code = status_code
        self.body = body
        super().__init__(f"Mercado Pago transient error (HTTP {status_code})")


class MercadoPagoClient(PaymentProvider):
    """Implementação concreta do port PaymentProvider usando o SDK oficial do Mercado Pago."""

    def __init__(self, sdk=None):
        """Inicializa com o SDK do Mercado Pago; `sdk` injetável para testes."""
        if sdk is None:
            import mercadopago  # lazy: só quando não injetado (adapter é o único a importar o SDK)

            sdk = mercadopago.SDK(getattr(settings, "MERCADOPAGO_ACCESS_TOKEN", ""))
        self._sdk = sdk

    def _log_request(self, operation: str, status: int | None, duration_ms: float, error: str | None = None) -> None:
        """Loga a chamada ao Mercado Pago de forma estruturada (sem PII)."""
        log_data = {
            "event": "mercadopago_request",
            "operation": operation,
            "status": status,
            "attempt": get_current_attempt(),
            "duration_ms": round(duration_ms, 2),
        }
        if error:
            log_data["error"] = error
        if error or (status is not None and status >= 400):
            logger.warning("Mercado Pago request failed", extra=log_data)
        else:
            logger.info("Mercado Pago request completed", extra=log_data)

    @staticmethod
    def _mapear_status(mp_status) -> StatusPagamento:
        """Mapeia o status cru do Mercado Pago para o estado de domínio."""
        if mp_status in _STATUS_APROVADO:
            return StatusPagamento.APROVADO
        if mp_status in _STATUS_RECUSADO:
            return StatusPagamento.RECUSADO
        return StatusPagamento.PENDENTE

    def _unwrap(self, result: dict, operation: str) -> dict:
        """Traduz o dict {status, response} do SDK: 2xx→dict; 5xx→retentável; 4xx/corpo inválido→PaymentProviderError."""
        status = result.get("status")
        body = result.get("response")
        if status is not None and 200 <= status < 300:
            if not isinstance(body, dict):
                raise PaymentProviderError(
                    message=f"Corpo inesperado do Mercado Pago em {operation}",
                    upstream_status=status,
                    upstream_body=body,
                )
            return body
        if status is not None and status >= 500:
            raise _TransientMPError(status, body)
        raise PaymentProviderError(
            message=f"Erro do Mercado Pago em {operation} (HTTP {status})",
            upstream_status=status,
            upstream_body=body,
        )

    @with_retry(max_attempts=3, backoff_seconds=[1, 2, 4], retriable_status_codes=_RETRIABLE_STATUS)
    def _request(self, operation: str, thunk) -> dict:
        """Executa uma chamada do SDK (via `thunk`) com retry em rede/5xx e log estruturado."""
        start = time.time()
        try:
            result = thunk()
        except (requests.ConnectionError, requests.Timeout) as e:
            self._log_request(operation, None, (time.time() - start) * 1000, error=str(e))
            raise
        self._log_request(operation, result.get("status"), (time.time() - start) * 1000)
        return self._unwrap(result, operation)

    def _execute(self, operation: str, thunk) -> dict:
        """Roda `_request` e garante que toda falha de integração vire PaymentProviderError (AD-6)."""
        try:
            return self._request(operation, thunk)
        except _TransientMPError as e:
            raise PaymentProviderError(
                message=f"Mercado Pago indisponível em {operation} (HTTP {e.status_code})",
                upstream_status=e.status_code,
                upstream_body=e.body,
            ) from e
        except (requests.ConnectionError, requests.Timeout) as e:
            raise PaymentProviderError(
                message=f"Mercado Pago inacessível em {operation}",
                upstream_status=None,
                upstream_body=str(e),
            ) from e

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
        """
        Cria um pagamento **Pix** (Checkout Transparente) e devolve o id do
        pagamento + o QR (código copia-e-cola e imagem PNG base64).

        Pix only: em vez do Checkout Pro (redirect), gera o Pix direto pela
        API de Pagamentos, exibido no app pra pessoa pagar sem sair do site.
        A idempotência de duplicidade é garantida a montante (CheckoutView
        reusa o pagamento já criado sob lock).
        """
        backend_url = getattr(settings, "BACKEND_PUBLIC_URL", "").rstrip("/")

        payer: dict = {"email": email}
        nome_limpo = (nome or "").strip()
        if nome_limpo:
            payer["first_name"] = nome_limpo
        if cpf_cnpj:
            tipo = "CNPJ" if len(cpf_cnpj) == 14 else "CPF"
            payer["identification"] = {"type": tipo, "number": cpf_cnpj}

        payment_data = {
            "transaction_amount": round(valor_centavos / 100, 2),
            "description": descricao,
            "payment_method_id": "pix",
            "external_reference": str(pedido_id),
            "payer": payer,
        }
        # O Mercado Pago exige uma URL pública HTTPS no notification_url e
        # rejeita http/localhost (400). Em local (http://localhost) omitimos —
        # sem webhook, o status é acompanhado pelo polling da confirmação. Em
        # staging/prod (https://api.clama.me) o webhook é incluído.
        if backend_url.startswith("https://"):
            payment_data["notification_url"] = (
                f"{backend_url}/api/webhooks/mercadopago/"
            )
            logger.info(
                "Pix criado COM notification_url",
                extra={
                    "event": "pix_notification_url_set",
                    "notification_url": payment_data["notification_url"],
                },
            )
        else:
            # Sem notification_url o Mercado Pago não entrega webhook por
            # pagamento — o pedido fica preso em AGUARDANDO_PAGAMENTO. Logamos
            # em nível WARNING para não ficar invisível (BACKEND_PUBLIC_URL
            # ausente/não-https em prod é misconfig crítico).
            logger.warning(
                "Pix criado SEM notification_url — BACKEND_PUBLIC_URL não-https; webhook não será entregue",
                extra={
                    "event": "pix_notification_url_missing",
                    "backend_url": backend_url or "(vazio)",
                },
            )

        response = self._execute(
            "payment_create", lambda: self._sdk.payment().create(payment_data)
        )

        transaction_data = (response.get("point_of_interaction") or {}).get(
            "transaction_data"
        ) or {}
        qr_code = transaction_data.get("qr_code")
        qr_code_base64 = transaction_data.get("qr_code_base64")
        payment_id = response.get("id")

        if not payment_id or not qr_code:
            raise PaymentProviderError(
                message="Resposta do Mercado Pago sem id/QR Pix ao criar cobrança",
                upstream_status=None,
                upstream_body=response,
            )

        return CobrancaResult(
            provider_payment_id=str(payment_id),
            checkout_url=transaction_data.get("ticket_url") or "",
            pix_qr_code=qr_code,
            pix_qr_code_base64=qr_code_base64,
        )

    def buscar_pagamento(self, payment_id: str) -> PagamentoResult:
        """Consulta um pagamento no Mercado Pago e devolve o estado de domínio mapeado."""
        response = self._execute(
            "payment_get", lambda: self._sdk.payment().get(payment_id)
        )
        return PagamentoResult(
            status=self._mapear_status(response.get("status")),
            external_reference=response.get("external_reference"),
            raw_status=response.get("status"),
        )

    def validar_assinatura(self, request) -> bool:
        """Valida o HMAC-SHA256 do x-signature do webhook Mercado Pago (AD-3); True se autêntico."""
        # Delega à função canônica de módulo — mesma lógica usada pelo middleware (HMAC num lugar só).
        return verificar_assinatura_webhook(request)

    def parse_notification(self, payload: dict, query: dict) -> Notificacao:
        """Normaliza o webhook: tipo do body, `data.id` do query (valor assinado)."""
        return Notificacao(tipo=payload.get("type", ""), data_id=query.get("data.id"))


def _parse_signature(header: str) -> tuple[str | None, str | None]:
    """Extrai `ts` e `v1` do header x-signature do Mercado Pago (formato `ts=...,v1=...`)."""
    ts = v1 = None
    for part in header.split(","):
        key, _, value = part.strip().partition("=")
        if key == "ts":
            ts = value
        elif key == "v1":
            v1 = value
    return ts, v1


def verificar_assinatura_webhook(request) -> bool:
    """
    Valida o HMAC-SHA256 do header `x-signature` do webhook Mercado Pago (AD-3).

    Fonte canônica da validação de assinatura — usada pelo adapter
    (`MercadoPagoClient.validar_assinatura`) e pelo middleware de MP.5.
    Não lê `request.body` (evita conflito de stream com o parser do DRF).
    Retorna False (nunca levanta) em qualquer falha.
    """
    secret = getattr(settings, "MERCADOPAGO_WEBHOOK_SECRET", "")
    if not secret:
        logger.warning(
            "Mercado Pago webhook auth: secret não configurado",
            extra={"event": "mercadopago_webhook_auth", "ok": False},
        )
        return False

    data_id = request.GET.get("data.id", "")
    request_id = request.headers.get("x-request-id", "")
    ts, v1 = _parse_signature(request.headers.get("x-signature", ""))
    if not (ts and v1 and data_id):
        logger.warning(
            "Mercado Pago webhook auth: assinatura ausente ou malformada",
            extra={"event": "mercadopago_webhook_auth", "ok": False},
        )
        return False

    manifest = f"id:{data_id.lower()};request-id:{request_id};ts:{ts};"
    expected = hmac.new(secret.encode(), manifest.encode(), hashlib.sha256).hexdigest()
    try:
        ok = hmac.compare_digest(expected, v1)
    except TypeError:
        # v1 vem do header do atacante; caracteres não-ASCII fazem compare_digest levantar.
        ok = False
    logger.info(
        "Mercado Pago webhook auth",
        extra={"event": "mercadopago_webhook_auth", "ok": ok},
    )
    return ok
