"""Comando de invalidação em massa dos refresh legados (Story 1.8 / AC4)."""

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken

User = get_user_model()
SENHA = "Senha-Forte-12345!"


@pytest.fixture
def customer(db):
    return User.objects.create_user(email="inval@example.com", password=SENHA)


def _login(client, email):
    resp = client.post(
        reverse("users:customer-login"),
        {"email": email, "password": SENHA},
        format="json",
    )
    assert resp.status_code == status.HTTP_200_OK
    return resp


@pytest.mark.django_db
class TestInvalidarRefreshTokensLegados:
    def test_dry_run_nao_grava_nada(self, customer):
        _login(APIClient(), customer.email)
        antes = BlacklistedToken.objects.count()

        call_command("invalidar_refresh_tokens_legados", "--dry-run")

        assert BlacklistedToken.objects.count() == antes

    def test_invalida_sessao_ativa(self, customer):
        client = APIClient()
        _login(client, customer.email)
        # A sessão funciona antes do comando.
        assert (
            client.get(reverse("users:customer-me")).status_code == status.HTTP_200_OK
        )

        call_command("invalidar_refresh_tokens_legados")

        # O refresh deixa de renovar — a sessão não se sustenta.
        assert (
            client.post(
                reverse("users:customer-refresh"), {}, format="json"
            ).status_code
            == status.HTTP_401_UNAUTHORIZED
        )

    def test_e_idempotente(self, customer):
        _login(APIClient(), customer.email)
        call_command("invalidar_refresh_tokens_legados")
        depois_da_primeira = BlacklistedToken.objects.count()

        call_command("invalidar_refresh_tokens_legados")

        assert BlacklistedToken.objects.count() == depois_da_primeira
