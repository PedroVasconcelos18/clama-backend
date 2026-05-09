"""
Handlers customizados para exceções DRF.
"""

from rest_framework.exceptions import (
    AuthenticationFailed,
    NotAuthenticated,
    Throttled,
)
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

from clama.core.pastoral_messages import MSG_RATE_LIMITED

from .exceptions import ClamaBaseException


def pastoral_exception_handler(exc, context):
    """
    Handler de exceções personalizado que converte ClamaBaseException
    para o formato pastoral de erro da API Clama.

    Formato de resposta:
    {
        "error": {
            "code": "nome_curto",
            "message": "mensagem técnica",
            "pastoral_message": "mensagem acolhedora"
        }
    }
    """
    if isinstance(exc, ClamaBaseException):
        status = getattr(exc, "status_code", 400)
        return Response(
            {
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "pastoral_message": exc.pastoral_message,
                }
            },
            status=status,
        )

    # Rate limiting (429 Throttled)
    if isinstance(exc, Throttled):
        wait_seconds = int(exc.wait) if exc.wait else 60
        return Response(
            {
                "error": {
                    "code": "rate_limited",
                    "message": f"Too many requests. Retry after {wait_seconds} seconds.",
                    "pastoral_message": MSG_RATE_LIMITED,
                }
            },
            status=429,
        )

    # P-16 (G2.a): pastoraliza 401 do paywall. `IsAuthenticated` levanta
    # `NotAuthenticated` quando o usuário é anônimo; algumas auth backends
    # do DRF levantam `AuthenticationFailed` para credenciais inválidas
    # (ex.: Bearer expirado). Em ambos os casos queremos a mesma mensagem
    # pastoral genérica. Se a exceção foi levantada com um detail dict
    # já no formato pastoral (caso de `CustomerLogoutView` cross-user e
    # outros), preserva o payload original — apenas transforma quando
    # o detail é a string genérica do DRF.
    if isinstance(exc, (NotAuthenticated, AuthenticationFailed)):
        detail = getattr(exc, "detail", None)
        if isinstance(detail, dict) and "error" in detail:
            return Response(detail, status=exc.status_code)
        return Response(
            {
                "error": {
                    "code": "not_authenticated",
                    "message": "Authentication required",
                    "pastoral_message": "Faça login pra continuar.",
                }
            },
            status=exc.status_code,
        )

    # Fallback para o handler padrão do DRF
    return drf_exception_handler(exc, context)
