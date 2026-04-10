"""
Views do app core.
"""
from rest_framework.response import Response
from rest_framework.views import APIView


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
