"""
Handlers customizados para exceções DRF.
"""
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

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

    # Fallback para o handler padrão do DRF
    return drf_exception_handler(exc, context)
