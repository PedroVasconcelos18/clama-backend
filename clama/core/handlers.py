"""
Handlers customizados para exceções DRF.
"""

from rest_framework.exceptions import Throttled
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
        error_body = {
            "code": exc.code,
            "message": exc.message,
            "pastoral_message": exc.pastoral_message,
        }
        # Merge campos extras (ex.: `redirect`) sem permitir override dos
        # campos canônicos — defesa contra collision acidental.
        for k, v in (getattr(exc, "extra", None) or {}).items():
            if k not in error_body:
                error_body[k] = v
        return Response({"error": error_body}, status=status)

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

    # Fallback para o handler padrão do DRF
    return drf_exception_handler(exc, context)
