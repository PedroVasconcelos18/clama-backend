"""Middleware do app blog.

`BuildTokenAuthMiddleware` marca requests Vike-build em staging (header
`X-Build-Token` matchando `settings.BUILD_API_TOKEN`). Não bloqueia nem
libera nada por si só — apenas adiciona `request.is_build_token` que
middlewares de restrição posterior (ex.: IP allowlist) podem consultar
pra liberar bypass autorizado.

Em produção, `BUILD_API_TOKEN` fica vazio (API pública sem restrição) e
o middleware é um no-op.
"""

import secrets

from django.conf import settings


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
