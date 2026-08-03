"""
Autenticação JWT por cookie `HttpOnly`.

O `JWTAuthentication` do simplejwt lê exclusivamente o header `Authorization`.
Com o token migrado para cookie com escopo `Path=/api` (ADR-01), o header deixa
de existir e a autenticação precisa ler do cookie.

O escopo por path é o que impede o servidor WordPress de receber a credencial:
o navegador não envia o cookie em requisições a `/blog/*`. `Domain=.clama.me`
não é alternativa — um cookie de domínio pai é enviado também para o blog, que
é exatamente a garantia que este desenho existe para dar.
"""

from django.conf import settings
from rest_framework_simplejwt.authentication import JWTAuthentication


class CookieJWTAuthentication(JWTAuthentication):
    """Lê o access token do cookie em vez do header `Authorization`."""

    def authenticate(self, request):
        raw_token = request.COOKIES.get(settings.AUTH_COOKIE_ACCESS)
        if not raw_token:
            return None
        validated_token = self.get_validated_token(raw_token)
        return self.get_user(validated_token), validated_token


def _cookie_kwargs() -> dict:
    """Atributos comuns aos cookies de autenticação."""
    return {
        "httponly": settings.AUTH_COOKIE_HTTPONLY,
        "secure": settings.AUTH_COOKIE_SECURE,
        "samesite": settings.AUTH_COOKIE_SAMESITE,
        "path": settings.AUTH_COOKIE_PATH,
    }


def set_auth_cookies(response, access: str | None, refresh: str | None = None):
    """
    Grava os cookies de autenticação na resposta.

    Chamar apenas no final do caminho feliz: `ATOMIC_REQUESTS` está ligado, e
    uma view que seta o cookie e depois levanta ainda emite o cookie enquanto o
    banco faz rollback.
    """
    if access:
        response.set_cookie(
            settings.AUTH_COOKIE_ACCESS,
            access,
            max_age=int(settings.SIMPLE_JWT["ACCESS_TOKEN_LIFETIME"].total_seconds()),
            **_cookie_kwargs(),
        )
    if refresh:
        response.set_cookie(
            settings.AUTH_COOKIE_REFRESH,
            refresh,
            max_age=int(settings.SIMPLE_JWT["REFRESH_TOKEN_LIFETIME"].total_seconds()),
            **_cookie_kwargs(),
        )
    return response


def clear_auth_cookies(response):
    """
    Remove os cookies de autenticação.

    `path` precisa bater exatamente com o da emissão — sem isso o navegador
    ignora a remoção e a resposta parece bem-sucedida com o cookie intacto.
    """
    for nome in (settings.AUTH_COOKIE_ACCESS, settings.AUTH_COOKIE_REFRESH):
        response.delete_cookie(
            nome,
            path=settings.AUTH_COOKIE_PATH,
            samesite=settings.AUTH_COOKIE_SAMESITE,
        )
    return response
