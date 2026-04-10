"""
Views do app core.
"""
from django.db import connection
from django.utils.timezone import now
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
