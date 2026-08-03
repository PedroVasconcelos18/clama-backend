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
from django.middleware.csrf import CsrfViewMiddleware
from rest_framework_simplejwt.authentication import JWTAuthentication

from clama.core.exceptions import PastoralAPIException

MSG_CSRF = (
    "Não conseguimos confirmar que este pedido veio de você. "
    "Recarregue a página e tente de novo."
)


class CSRFInvalidoError(PastoralAPIException):
    """403 em escrita autenticada por cookie sem prova de CSRF válida."""

    status_code = 403
    code = "csrf_invalido"
    message = "CSRF verification failed"
    pastoral_message = MSG_CSRF


class _CSRFCheck(CsrfViewMiddleware):
    """Expõe a validação de CSRF do Django fora do ciclo de middleware."""

    def _reject(self, request, reason):
        return reason


class CookieJWTAuthentication(JWTAuthentication):
    """
    Lê o access token do cookie em vez do header `Authorization` e aplica CSRF.

    O CSRF aqui não é opcional. Autenticação por header era imune por
    construção — o navegador nunca anexa `Authorization` sozinho. Cookie é
    enviado automaticamente, então o vetor nasce junto com a migração.

    E o `SessionAuthentication` do default global **não** cobre este caso: o DRF
    para na primeira classe que autentica, e como esta devolve um usuário, o
    `enforce_csrf` daquela nunca roda. Sem a checagem abaixo, toda escrita
    autenticada por cookie ficaria descoberta.
    """

    def authenticate(self, request):
        raw_token = request.COOKIES.get(settings.AUTH_COOKIE_ACCESS)
        if not raw_token:
            return None
        validated_token = self.get_validated_token(raw_token)
        user = self.get_user(validated_token)
        self.enforce_csrf(request)
        return user, validated_token

    def enforce_csrf(self, request) -> None:
        """Rejeita métodos não-seguros sem prova de CSRF válida."""
        if request.method in ("GET", "HEAD", "OPTIONS", "TRACE"):
            return
        checker = _CSRFCheck(lambda req: None)
        checker.process_request(request)
        motivo = checker.process_view(request, None, (), {})
        if motivo:
            raise CSRFInvalidoError()


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
