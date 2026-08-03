"""Middleware do app blog.

`WordPressWebhookAuthMiddleware` autentica o webhook de publicação do
WordPress antes de ele tocar a view (Story 3.2).

`BuildTokenAuthMiddleware` marca requests Vike-build em staging (header
`X-Build-Token` matchando `settings.BUILD_API_TOKEN`). Não bloqueia nem
libera nada por si só — apenas adiciona `request.is_build_token` que
middlewares de restrição posterior (ex.: IP allowlist) podem consultar
pra liberar bypass autorizado.

Em produção, `BUILD_API_TOKEN` fica vazio (API pública sem restrição) e
o middleware é um no-op.
"""

import logging
import secrets

from django.conf import settings
from django.http import JsonResponse

from clama.blog.services.wordpress_webhook import verificar_assinatura_webhook

logger = logging.getLogger("clama.blog.webhook_auth")


def _ip_do_cliente(request) -> str:
    """IP do cliente, considerando proxies."""
    encaminhado = request.META.get("HTTP_X_FORWARDED_FOR")
    if encaminhado:
        return encaminhado.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "unknown")


def _resposta_nao_autorizado() -> JsonResponse:
    """401 no envelope pastoral de três chaves."""
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


class WordPressWebhookAuthMiddleware:
    """Autentica o webhook de publicação do WordPress (Story 3.2).

    Assinatura inválida ou ausente → 401 **sem chamar `get_response`**. Isso é
    o AC2: sem tocar a view, o endpoint não vira vetor de carga — ninguém
    consegue fazer o Clama enfileirar task Celery mandando POST sem segredo.

    A lógica canônica de HMAC vive em
    `services/wordpress_webhook.verificar_assinatura_webhook`; aqui só se
    traduz o resultado.

    ⚠️ Ao contrário do middleware do Mercado Pago, este **lê `request.body`** —
    o WordPress assina o corpo cru. É seguro: o Django cacheia o `body` no
    primeiro acesso e o DRF relê dos bytes cacheados.
    """

    PROTECTED_PATH = "/api/webhooks/wordpress/"

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Fast-path: qualquer outra rota passa sem tocar em nada.
        if request.path != self.PROTECTED_PATH:
            return self.get_response(request)

        if not verificar_assinatura_webhook(request):
            logger.warning(
                "wordpress_webhook_auth_failed",
                extra={
                    "event": "wordpress_webhook_auth",
                    "ok": False,
                    "ip": _ip_do_cliente(request),
                },
            )
            return _resposta_nao_autorizado()

        return self.get_response(request)


class BuildTokenAuthMiddleware:
    """Marca requests Vike-build com `request.is_build_token = True`."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        configured = settings.BUILD_API_TOKEN or ""
        received = request.META.get("HTTP_X_BUILD_TOKEN", "") or ""
        # `secrets.compare_digest` é constant-time — defesa contra timing
        # attacks (token é shared secret, baixo risco prático, mas custa
        # nada e é boa prática).
        request.is_build_token = bool(
            configured and received and secrets.compare_digest(configured, received)
        )
        return self.get_response(request)
