"""
Middleware de autenticação para webhooks do Asaas.
"""

import hmac
import logging

from django.conf import settings
from django.http import JsonResponse

logger = logging.getLogger("clama.payments.webhook_auth")


class AsaasWebhookAuthMiddleware:
    """
    Autentica webhooks inbound do Asaas via token estático no header
    `asaas-access-token`, comparado em tempo constante ao
    `settings.ASAAS_WEBHOOK_SECRET`.

    NOTA: Asaas atualmente usa token estático em vez de HMAC assinado.
    Quando/se Asaas migrar para HMAC, substituir a comparação por:

        import hashlib
        computed = hmac.new(secret.encode(), request.body, hashlib.sha256).hexdigest()
        valid = hmac.compare_digest(computed, header_signature)

    O middleware precisa então ler `request.body` ANTES de a view consumir
    o stream — usar `request._body` cache ou `request.body` direto.
    """

    PROTECTED_PATH = "/api/webhooks/asaas/"

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Fast-path: outras rotas passam direto sem validação
        if request.path != self.PROTECTED_PATH:
            return self.get_response(request)

        # Validação do token
        secret = getattr(settings, "ASAAS_WEBHOOK_SECRET", None)
        if not secret:
            logger.error(
                "ASAAS_WEBHOOK_SECRET not configured",
                extra={
                    "event": "asaas_webhook_auth",
                    "ok": False,
                    "reason": "secret_not_configured",
                },
            )
            return self._unauthorized_response()

        # Ler token do header
        header_token = request.headers.get("asaas-access-token", "")

        # Comparação em tempo constante para evitar timing attacks
        if not header_token or not hmac.compare_digest(secret, header_token):
            remote_ip = self._get_client_ip(request)
            logger.warning(
                "Asaas webhook auth failed",
                extra={
                    "event": "asaas_webhook_auth",
                    "ok": False,
                    "ip": remote_ip,
                },
            )
            return self._unauthorized_response()

        # Token válido
        remote_ip = self._get_client_ip(request)
        logger.info(
            "Asaas webhook auth success",
            extra={
                "event": "asaas_webhook_auth",
                "ok": True,
                "ip": remote_ip,
            },
        )

        return self.get_response(request)

    def _get_client_ip(self, request) -> str:
        """Obtém IP do cliente, considerando proxies."""
        x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
        if x_forwarded_for:
            return x_forwarded_for.split(",")[0].strip()
        return request.META.get("REMOTE_ADDR", "unknown")

    def _unauthorized_response(self) -> JsonResponse:
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
