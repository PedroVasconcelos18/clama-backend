"""
Middleware de autenticação para webhooks do Mercado Pago.
"""

import logging

from django.http import JsonResponse

from clama.payments.services.mercadopago_client import verificar_assinatura_webhook

logger = logging.getLogger("clama.payments.webhook_auth")


def _get_client_ip(request) -> str:
    """Obtém IP do cliente, considerando proxies."""
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded_for:
        return x_forwarded_for.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "unknown")


def _unauthorized_response() -> JsonResponse:
    """Retorna resposta 401 no formato pastoral."""
    return JsonResponse(
        {
            "error": {
                "code": "unauthorized",
                "message": "Authentication required",
                "pastoral_message": "Não pudemos confirmar quem enviou essa requisição.",
            }
        },
        status=401,
    )


class MercadoPagoWebhookAuthMiddleware:
    """
    Autentica webhooks inbound do Mercado Pago validando o HMAC-SHA256 do header
    `x-signature` (AD-3), antes de a requisição tocar a view. Assinatura inválida,
    header ausente ou secret não configurado → 401 pastoral.

    A lógica canônica de HMAC vive em `mercadopago_client.verificar_assinatura_webhook`
    (mesma usada pelo adapter) — o middleware apenas a chama e traduz o resultado.
    Não lê `request.body` (sem conflito de stream com o parser do DRF).
    """

    PROTECTED_PATH = "/api/webhooks/mercadopago/"

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Fast-path: outras rotas passam direto sem validação
        if request.path != self.PROTECTED_PATH:
            return self.get_response(request)

        if not verificar_assinatura_webhook(request):
            logger.warning(
                "Mercado Pago webhook auth failed",
                extra={
                    "event": "mercadopago_webhook_auth",
                    "ok": False,
                    "ip": _get_client_ip(request),
                },
            )
            return _unauthorized_response()

        return self.get_response(request)
