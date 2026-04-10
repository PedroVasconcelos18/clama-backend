"""
Testes para as exceções pastorais do Clama.
"""
import pytest
from django.test import override_settings
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory

from clama.core.exceptions import ClamaBaseException, PastoralAPIException
from clama.core.handlers import pastoral_exception_handler


class TestClamaBaseException:
    """Testes para ClamaBaseException."""

    def test_default_values(self):
        """Exceção deve ter valores padrão."""
        exc = ClamaBaseException()
        assert exc.code == "clama_error"
        assert exc.message == "Erro"
        assert exc.pastoral_message == "Algo não saiu como o esperado."

    def test_custom_values(self):
        """Exceção deve aceitar valores customizados."""
        exc = ClamaBaseException(
            message="Erro técnico",
            code="custom_error",
            pastoral_message="Algo deu errado, tente novamente.",
        )
        assert exc.code == "custom_error"
        assert exc.message == "Erro técnico"
        assert exc.pastoral_message == "Algo deu errado, tente novamente."


class TestPastoralAPIException:
    """Testes para PastoralAPIException."""

    def test_default_status_code(self):
        """Exceção deve ter status 400 por padrão."""
        exc = PastoralAPIException()
        assert exc.status_code == 400

    def test_custom_status_code(self):
        """Exceção deve aceitar status customizado."""
        exc = PastoralAPIException(status_code=404)
        assert exc.status_code == 404


class TestPastoralExceptionHandler:
    """Testes para o handler de exceções pastoral."""

    def test_handles_clama_exception(self):
        """Handler deve converter ClamaBaseException para Response pastoral."""
        exc = PastoralAPIException(
            message="Pedido não encontrado",
            code="order_not_found",
            pastoral_message="Não encontramos seu pedido. Verifique o código.",
            status_code=404,
        )
        response = pastoral_exception_handler(exc, context={})

        assert response.status_code == 404
        assert response.data == {
            "error": {
                "code": "order_not_found",
                "message": "Pedido não encontrado",
                "pastoral_message": "Não encontramos seu pedido. Verifique o código.",
            }
        }

    def test_view_raises_pastoral_exception(self):
        """View DRF que lança PastoralAPIException deve retornar payload pastoral."""
        factory = APIRequestFactory()

        @api_view(["GET"])
        def failing_view(request):
            raise PastoralAPIException(
                message="Erro de validação",
                code="validation_error",
                pastoral_message="Por favor, verifique os dados informados.",
                status_code=422,
            )

        request = factory.get("/")
        response = failing_view(request)

        assert response.status_code == 422
        assert "error" in response.data
        assert response.data["error"]["code"] == "validation_error"
        assert response.data["error"]["pastoral_message"] == "Por favor, verifique os dados informados."
