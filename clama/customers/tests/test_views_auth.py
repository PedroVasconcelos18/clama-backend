"""
Testes dos endpoints `/api/customer/auth/*` e `/api/customer/me/`.
"""

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status as drf_status
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

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
    def test_login_credenciais_validas_retorna_tokens_e_user(
        self, api_client, customer
    ):
        response = _login(api_client, customer.email, CUSTOMER_PASSWORD)
        assert response.status_code == drf_status.HTTP_200_OK
        assert "access" in response.data
        assert "refresh" in response.data
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
        login_resp = _login(api_client, customer.email, CUSTOMER_PASSWORD)
        refresh = login_resp.data["refresh"]

        resp = api_client.post(
            reverse("customers:refresh"),
            {"refresh": refresh},
            format="json",
        )
        assert resp.status_code == drf_status.HTTP_200_OK
        assert "access" in resp.data
        # ROTATE_REFRESH_TOKENS=True — vem refresh novo.
        assert "refresh" in resp.data
        assert resp.data["refresh"] != refresh

        # Refresh antigo deve estar blacklisted (BLACKLIST_AFTER_ROTATION).
        resp2 = api_client.post(
            reverse("customers:refresh"),
            {"refresh": refresh},
            format="json",
        )
        assert resp2.status_code == drf_status.HTTP_401_UNAUTHORIZED


@pytest.mark.django_db
class TestCustomerLogout:
    def test_logout_idempotente_token_invalido(self, api_client, customer):
        login_resp = _login(api_client, customer.email, CUSTOMER_PASSWORD)
        access = login_resp.data["access"]

        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")

        # Refresh inválido — ainda 200.
        resp = api_client.post(
            reverse("customers:logout"),
            {"refresh": "lixo-invalido"},
            format="json",
        )
        assert resp.status_code == drf_status.HTTP_200_OK

    def test_logout_idempotente_sem_refresh_no_body(self, api_client, customer):
        login_resp = _login(api_client, customer.email, CUSTOMER_PASSWORD)
        access = login_resp.data["access"]
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")

        resp = api_client.post(reverse("customers:logout"), {}, format="json")
        assert resp.status_code == drf_status.HTTP_200_OK

    def test_logout_token_valido_blacklist_e_revoga_refresh(
        self, api_client, customer
    ):
        login_resp = _login(api_client, customer.email, CUSTOMER_PASSWORD)
        access = login_resp.data["access"]
        refresh = login_resp.data["refresh"]
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")

        resp = api_client.post(
            reverse("customers:logout"),
            {"refresh": refresh},
            format="json",
        )
        assert resp.status_code == drf_status.HTTP_200_OK

        # Tentar usar o refresh blacklisted falha.
        resp2 = api_client.post(
            reverse("customers:refresh"),
            {"refresh": refresh},
            format="json",
        )
        assert resp2.status_code == drf_status.HTTP_401_UNAUTHORIZED

    def test_logout_idempotente_segunda_chamada_com_mesmo_refresh(
        self, api_client, customer
    ):
        """Segundo logout do mesmo refresh = 200 (já blacklistado)."""
        login_resp = _login(api_client, customer.email, CUSTOMER_PASSWORD)
        access = login_resp.data["access"]
        refresh = login_resp.data["refresh"]
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")

        # Primeira: blacklist.
        api_client.post(
            reverse("customers:logout"),
            {"refresh": refresh},
            format="json",
        )
        # Segunda: já blacklisted — ainda 200.
        resp = api_client.post(
            reverse("customers:logout"),
            {"refresh": refresh},
            format="json",
        )
        assert resp.status_code == drf_status.HTTP_200_OK


@pytest.mark.django_db
class TestChangePassword:
    def test_change_password_force_change_aceita_temp_e_zera_flag(
        self, api_client, customer_force_change
    ):
        login_resp = _login(api_client, customer_force_change.email, TEMP_PASSWORD)
        assert login_resp.status_code == drf_status.HTTP_200_OK
        access = login_resp.data["access"]
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")

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

    def test_change_password_senha_atual_errada_retorna_400(
        self, api_client, customer
    ):
        login_resp = _login(api_client, customer.email, CUSTOMER_PASSWORD)
        access = login_resp.data["access"]
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")

        resp = api_client.post(
            reverse("customers:change-password"),
            {"senha_atual": "errada", "nova_senha": "Senha-Nova-XYZ-987!"},
            format="json",
        )
        assert resp.status_code == drf_status.HTTP_400_BAD_REQUEST

    def test_change_password_nova_senha_aplica_password_validators(
        self, api_client, customer
    ):
        login_resp = _login(api_client, customer.email, CUSTOMER_PASSWORD)
        access = login_resp.data["access"]
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")

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
        login_resp = _login(api_client, customer.email, CUSTOMER_PASSWORD)
        access = login_resp.data["access"]
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")

        resp = api_client.get(reverse("customers:me"))
        assert resp.status_code == drf_status.HTTP_200_OK
        assert resp.data["email"] == customer.email
        assert resp.data["nome_completo"] == "Maria Silva"
        assert resp.data["force_change_password"] is False
        assert resp.data["freemium_used_at"] is None

    def test_me_acessivel_mesmo_com_force_change_password(
        self, api_client, customer_force_change
    ):
        """`/me/` é deliberadamente isento de IsCustomerPasswordCurrent."""
        login_resp = _login(api_client, customer_force_change.email, TEMP_PASSWORD)
        access = login_resp.data["access"]
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")

        resp = api_client.get(reverse("customers:me"))
        assert resp.status_code == drf_status.HTTP_200_OK
        assert resp.data["force_change_password"] is True
