"""
Testes dos endpoints `/api/customer/auth/*` e `/api/customer/me/`.
"""

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status as drf_status
from rest_framework.test import APIClient

User = get_user_model()


CUSTOMER_PASSWORD = "Senha-Forte-12345!"
TEMP_PASSWORD = "TempPassword-XYZ-9876!"


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def customer(db):
    return User.objects.create_user(
        email="customer@example.com",
        password=CUSTOMER_PASSWORD,
        nome_completo="Maria Silva",
        cpf_cnpj="12345678901",
        telefone="+5511999998888",
    )


@pytest.fixture
def customer_force_change(db):
    return User.objects.create_user(
        email="force@example.com",
        password=TEMP_PASSWORD,
        nome_completo="Bob Marley",
        force_change_password=True,
    )


@pytest.fixture
def admin_user(db):
    return User.objects.create_user(
        email="admin@example.com",
        password=CUSTOMER_PASSWORD,
        is_clama_admin=True,
    )


def _login(client, email, password):
    return client.post(
        reverse("customers:login"),
        {"email": email, "password": password},
        format="json",
    )


@pytest.mark.django_db
class TestCustomerLogin:
    def test_login_credenciais_validas_retorna_cookies_e_user(
        self, api_client, customer
    ):
        response = _login(api_client, customer.email, CUSTOMER_PASSWORD)
        assert response.status_code == drf_status.HTTP_200_OK
        # ADR-01: tokens vão para cookies HttpOnly; o corpo traz só o `user`.
        assert settings.AUTH_COOKIE_ACCESS in response.cookies
        assert settings.AUTH_COOKIE_REFRESH in response.cookies
        assert "access" not in response.data
        assert "refresh" not in response.data
        user = response.data["user"]
        assert user["email"] == customer.email
        assert user["nome_completo"] == "Maria Silva"
        assert user["force_change_password"] is False
        assert user["freemium_used_at"] is None

    def test_login_email_iexact_lookup_funciona(self, api_client, customer):
        """Login case-insensitive — alinha com F-17 do deferred-work."""
        response = _login(api_client, customer.email.upper(), CUSTOMER_PASSWORD)
        assert response.status_code == drf_status.HTTP_200_OK

    def test_login_email_inexistente_retorna_401_pastoral(self, api_client, db):
        response = _login(api_client, "ghost@example.com", "qualquer-senha")
        assert response.status_code == drf_status.HTTP_401_UNAUTHORIZED
        assert response.data["error"]["code"] == "customer_login_invalido"

    def test_login_senha_errada_retorna_401_mesma_msg(self, api_client, customer):
        """Sem oracle: email inexistente e senha errada respondem idêntico."""
        response = _login(api_client, customer.email, "senha-errada")
        assert response.status_code == drf_status.HTTP_401_UNAUTHORIZED
        assert response.data["error"]["code"] == "customer_login_invalido"

    def test_login_admin_rejeitado_com_msg_identica(self, api_client, admin_user):
        """Admin tentando logar via customer endpoint = 401 idêntico (sem oracle de role)."""
        response = _login(api_client, admin_user.email, CUSTOMER_PASSWORD)
        assert response.status_code == drf_status.HTTP_401_UNAUTHORIZED
        assert response.data["error"]["code"] == "customer_login_invalido"

    def test_login_user_inativo_rejeitado(self, api_client, customer):
        customer.is_active = False
        customer.save(update_fields=["is_active"])
        response = _login(api_client, customer.email, CUSTOMER_PASSWORD)
        assert response.status_code == drf_status.HTTP_401_UNAUTHORIZED


@pytest.mark.django_db
class TestCustomerRefresh:
    def test_refresh_valido_retorna_novo_access_e_blacklist_antigo(
        self, api_client, customer
    ):
        _login(api_client, customer.email, CUSTOMER_PASSWORD)
        refresh_antigo = api_client.cookies[settings.AUTH_COOKIE_REFRESH].value

        resp = api_client.post(reverse("customers:refresh"), {}, format="json")
        assert resp.status_code == drf_status.HTTP_200_OK
        assert settings.AUTH_COOKIE_ACCESS in resp.cookies
        # ROTATE_REFRESH_TOKENS=True — vem refresh novo.
        assert settings.AUTH_COOKIE_REFRESH in resp.cookies
        assert resp.cookies[settings.AUTH_COOKIE_REFRESH].value != refresh_antigo

        # Refresh antigo deve estar blacklisted (BLACKLIST_AFTER_ROTATION).
        api_client.cookies[settings.AUTH_COOKIE_REFRESH] = refresh_antigo
        resp2 = api_client.post(reverse("customers:refresh"), {}, format="json")
        assert resp2.status_code == drf_status.HTTP_401_UNAUTHORIZED


@pytest.mark.django_db
class TestCustomerLogout:
    """
    O logout responde 205 (não 200): `config/urls.py:39` inclui
    `clama_backend.users.api.urls` antes de `:41`, então é a view de `users`
    que atende estes caminhos. A implementação em `clama/customers/api/views.py`
    é código morto — ver o relatório de auditoria da Story 1.1.
    """

    def test_logout_sem_cookie_e_idempotente(self, api_client, customer):
        _login(api_client, customer.email, CUSTOMER_PASSWORD)
        del api_client.cookies[settings.AUTH_COOKIE_REFRESH]

        resp = api_client.post(reverse("customers:logout"), {}, format="json")
        assert resp.status_code == drf_status.HTTP_205_RESET_CONTENT

    def test_logout_revoga_o_refresh(self, api_client, customer):
        _login(api_client, customer.email, CUSTOMER_PASSWORD)
        refresh = api_client.cookies[settings.AUTH_COOKIE_REFRESH].value

        resp = api_client.post(reverse("customers:logout"), {}, format="json")
        assert resp.status_code == drf_status.HTTP_205_RESET_CONTENT

        # O refresh blacklistado não renova mais, mesmo reinjetado no cookie.
        api_client.cookies[settings.AUTH_COOKIE_REFRESH] = refresh
        resp2 = api_client.post(reverse("customers:refresh"), {}, format="json")
        assert resp2.status_code == drf_status.HTTP_401_UNAUTHORIZED

    def test_logout_segunda_chamada_com_mesmo_refresh_e_idempotente(
        self, api_client, customer
    ):
        _login(api_client, customer.email, CUSTOMER_PASSWORD)
        access = api_client.cookies[settings.AUTH_COOKIE_ACCESS].value
        refresh = api_client.cookies[settings.AUTH_COOKIE_REFRESH].value

        primeira = api_client.post(reverse("customers:logout"), {}, format="json")
        assert primeira.status_code == drf_status.HTTP_205_RESET_CONTENT

        # O logout limpou os dois cookies; reinjetamos para exercitar de fato o
        # caminho de idempotência com o mesmo refresh já blacklistado.
        api_client.cookies[settings.AUTH_COOKIE_ACCESS] = access
        api_client.cookies[settings.AUTH_COOKIE_REFRESH] = refresh
        segunda = api_client.post(reverse("customers:logout"), {}, format="json")
        assert segunda.status_code == drf_status.HTTP_205_RESET_CONTENT


@pytest.mark.django_db
class TestChangePassword:
    def test_change_password_force_change_aceita_temp_e_zera_flag(
        self, api_client, customer_force_change
    ):
        login_resp = _login(api_client, customer_force_change.email, TEMP_PASSWORD)
        assert login_resp.status_code == drf_status.HTTP_200_OK

        resp = api_client.post(
            reverse("customers:change-password"),
            {
                "senha_atual": TEMP_PASSWORD,
                "nova_senha": "Senha-Nova-XYZ-987!",
            },
            format="json",
        )
        assert resp.status_code == drf_status.HTTP_200_OK

        customer_force_change.refresh_from_db()
        assert customer_force_change.force_change_password is False
        assert customer_force_change.check_password("Senha-Nova-XYZ-987!")

    def test_change_password_senha_atual_errada_retorna_400(self, api_client, customer):
        _login(api_client, customer.email, CUSTOMER_PASSWORD)

        resp = api_client.post(
            reverse("customers:change-password"),
            {"senha_atual": "errada", "nova_senha": "Senha-Nova-XYZ-987!"},
            format="json",
        )
        assert resp.status_code == drf_status.HTTP_400_BAD_REQUEST

    def test_change_password_nova_senha_aplica_password_validators(
        self, api_client, customer
    ):
        _login(api_client, customer.email, CUSTOMER_PASSWORD)

        resp = api_client.post(
            reverse("customers:change-password"),
            {"senha_atual": CUSTOMER_PASSWORD, "nova_senha": "123"},
            format="json",
        )
        assert resp.status_code == drf_status.HTTP_400_BAD_REQUEST

    def test_change_password_anonimo_retorna_401(self, api_client, db):
        resp = api_client.post(
            reverse("customers:change-password"),
            {"senha_atual": "x", "nova_senha": "y"},
            format="json",
        )
        assert resp.status_code == drf_status.HTTP_401_UNAUTHORIZED


@pytest.mark.django_db
class TestCustomerMe:
    def test_me_anonimo_retorna_401(self, api_client, db):
        resp = api_client.get(reverse("customers:me"))
        assert resp.status_code == drf_status.HTTP_401_UNAUTHORIZED

    def test_me_autenticado_retorna_dados(self, api_client, customer):
        _login(api_client, customer.email, CUSTOMER_PASSWORD)

        resp = api_client.get(reverse("customers:me"))
        assert resp.status_code == drf_status.HTTP_200_OK
        assert resp.data["email"] == customer.email
        assert resp.data["nome_completo"] == "Maria Silva"
        assert resp.data["force_change_password"] is False
        assert resp.data["freemium_used_at"] is None
        # Dados de cadastro pra pré-preencher o form de pedido na /conta.
        assert resp.data["cpf_cnpj"] == "12345678901"
        assert resp.data["telefone"] == "+5511999998888"

    def test_me_acessivel_mesmo_com_force_change_password(
        self, api_client, customer_force_change
    ):
        """`/me/` é deliberadamente isento de IsCustomerPasswordCurrent."""
        _login(api_client, customer_force_change.email, TEMP_PASSWORD)

        resp = api_client.get(reverse("customers:me"))
        assert resp.status_code == drf_status.HTTP_200_OK
        assert resp.data["force_change_password"] is True
