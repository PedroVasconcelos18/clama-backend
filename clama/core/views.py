"""
Views do app core.
"""

from django.db import connection
from django.middleware.csrf import get_token
from django.utils.decorators import method_decorator
from django.utils.timezone import now
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework.response import Response
from rest_framework.views import APIView

from clama.core import __version__


class SentryDebugView(APIView):
    """
    View de debug para validar integração com Sentry.
    Disponível apenas em DEBUG=True.
    Lança ZeroDivisionError para testar captura de erros.
    """

    permission_classes = []

    def get(self, request):
        """Lança um erro para testar o Sentry."""
        division_by_zero = 1 / 0  # noqa: F841
        return Response({"message": "Esta linha nunca será alcançada"})


class HealthCheckView(APIView):
    """
    View de healthcheck para monitoramento.
    Verifica conexão com o banco de dados.
    Não requer autenticação.
    """

    permission_classes = []
    authentication_classes = []

    def get(self, request):
        """Retorna status de saúde do backend."""
        db_status = "ok"
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
        except Exception:
            db_status = "error"

        return Response(
            {
                "status": "ok",
                "version": __version__,
                "timestamp": now().isoformat().replace("+00:00", "Z"),
                "database": db_status,
            }
        )


class CSRFTokenView(APIView):
    """
    Entrega o token de CSRF para o cliente.

    `CSRF_COOKIE_HTTPONLY = True` impede o JavaScript de ler o cookie, então o
    padrão double-submit nativo do Django não funciona aqui. Este endpoint
    devolve o token no corpo; o cliente o mantém em memória e o reenvia no
    header `X-CSRFToken`.

    Isso é o que permite ao widget de comentários — que a partir do Epic 6 roda
    dentro de uma página servida pelo WordPress — obter a prova de CSRF **sem
    depender de nada que o WordPress precise fornecer** (AR-FRONTEIRAS: o
    WordPress nunca é autoridade sobre identidade).
    """

    permission_classes = []
    authentication_classes = []

    @method_decorator(ensure_csrf_cookie)
    def get(self, request):
        return Response({"csrf_token": get_token(request)})
