"""
Testes do conjunto Customer Auth (G2.a):
- POST /api/customer/auth/login/      (happy / force-change / admin / bad creds / rate-limit)
- POST /api/customer/auth/refresh/    (happy / blacklist após logout)
- POST /api/customer/auth/logout/     (happy / idempotência ao reusar refresh já blacklisted / cross-user DoS)
- GET  /api/customer/me/              (200 com flag true e false)
"""

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

User = get_user_model()


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def url_login():
    return reverse("users:customer-login")


@pytest.fixture
def url_refresh():
    return reverse("users:customer-refresh")


@pytest.fixture
def url_logout():
    return reverse("users:customer-logout")


@pytest.fixture
def url_me():
    return reverse("users:customer-me")


@pytest.fixture
def customer_user(db):
    return User.objects.create_user(
        email="alice@example.com",
        password="SenhaForte!123",
        nome_completo="Alice Maria",
    )


@pytest.fixture
def customer_force_change(db):
    return User.objects.create_user(
        email="bia@example.com",
        password="TempPwd!#999",
        nome_completo="Bia Souza",
        force_change_password=True,
    )


@pytest.fixture
def admin_user(db):
    return User.objects.create_user(
        email="admin@example.com",
        password="AdminPwd!#999",
        nome_completo="Admin Clama",
        is_clama_admin=True,
    )


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestCustomerLoginHappy:
    def test_login_happy_retorna_tokens_e_user(
        self, api_client, url_login, customer_user
    ):
        response = api_client.post(
            url_login,
            {"email": "alice@example.com", "password": "SenhaForte!123"},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        assert "access" in response.data
        assert "refresh" in response.data
        assert response.data["user"]["email"] == "alice@example.com"
        assert response.data["user"]["force_change_password"] is False
        assert response.data["user"]["freemium_used_at"] is None
        assert response.data["user"]["nome_completo"] == "Alice Maria"

    def test_login_email_case_insensitive(
        self, api_client, url_login, customer_user
    ):
        # `__iexact` deve permitir login com email em casing diferente.
        response = api_client.post(
            url_login,
            {"email": "ALICE@example.com", "password": "SenhaForte!123"},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK


@pytest.mark.django_db
class TestCustomerLoginForceChange:
    def test_login_com_flag_true_retorna_200_com_flag(
        self, api_client, url_login, customer_force_change
    ):
        response = api_client.post(
            url_login,
            {"email": "bia@example.com", "password": "TempPwd!#999"},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.data["user"]["force_change_password"] is True


@pytest.mark.django_db
class TestCustomerLoginAdminBlocked:
    def test_admin_em_endpoint_customer_recebe_401_generica(
        self, api_client, url_login, admin_user
    ):
        response = api_client.post(
            url_login,
            {"email": "admin@example.com", "password": "AdminPwd!#999"},
            format="json",
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        # Mensagem genérica idêntica a credenciais erradas (sem oracle de role).
        assert (
            response.data.get("error", {}).get("code") == "invalid_credentials"
        )


@pytest.mark.django_db
class TestCustomerLoginEmailAmbiguo:
    """
    P-5: defesa contra `MultipleObjectsReturned` no `__iexact`. Se por
    qualquer razão dois rows com mesmo email em casing diferente existirem
    (uniqueness CS no Postgres antes de F-17), o lookup `__iexact` levanta
    `MultipleObjectsReturned` — sem captura ia virar 500. Tratamos como
    credenciais inválidas (401 genérica).
    """

    def test_dois_users_mesmo_email_casing_diferente_retorna_401(
        self, api_client, url_login
    ):
        # Cria duas rows que poderiam coexistir antes de normalização
        # global. Como `unique=True` do Django respeita case na maioria dos
        # backends, usamos `bulk_create` para contornar e garantir o setup.
        u1 = User(email="duplo@example.com", nome_completo="Um")
        u1.set_password("SenhaForte!123")
        u2 = User(email="DUPLO@example.com", nome_completo="Dois")
        u2.set_password("SenhaForte!#999")
        # `bulk_create` ignora `unique` em SQLite (case-sensitive aqui).
        User.objects.bulk_create([u1, u2])

        response = api_client.post(
            url_login,
            {"email": "Duplo@example.com", "password": "SenhaForte!123"},
            format="json",
        )
        # Não pode ser 500 — deve cair na 401 genérica.
        assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.django_db
class TestCustomerLoginBadCreds:
    def test_email_inexistente_retorna_401(self, api_client, url_login):
        response = api_client.post(
            url_login,
            {"email": "ninguem@example.com", "password": "qualquer-coisa"},
            format="json",
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_senha_errada_retorna_401(
        self, api_client, url_login, customer_user
    ):
        response = api_client.post(
            url_login,
            {"email": "alice@example.com", "password": "errada-mesmo"},
            format="json",
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.django_db
class TestCustomerLoginRateLimit:
    """5/min/IP no scope `customer_login`. Testes em geral desabilitam throttle
    via settings; aqui ativamos pontualmente por override_settings."""

    @override_settings(
        REST_FRAMEWORK={
            "DEFAULT_AUTHENTICATION_CLASSES": (
                "rest_framework_simplejwt.authentication.JWTAuthentication",
                "rest_framework.authentication.SessionAuthentication",
            ),
            "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.AllowAny",),
            "DEFAULT_THROTTLE_CLASSES": (
                "rest_framework.throttling.ScopedRateThrottle",
            ),
            "DEFAULT_THROTTLE_RATES": {
                "customer_login": "5/min",
            },
            "EXCEPTION_HANDLER": "clama.core.handlers.pastoral_exception_handler",
            "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
        }
    )
    def test_sexta_request_no_minuto_recebe_429(
        self, api_client, url_login, customer_user
    ):
        cache.clear()
        for i in range(5):
            response = api_client.post(
                url_login,
                {"email": "alice@example.com", "password": "SenhaForte!123"},
                format="json",
            )
            assert response.status_code in (
                status.HTTP_200_OK,
                status.HTTP_401_UNAUTHORIZED,
            ), f"req {i+1} retornou {response.status_code}"
        # Sexta tentativa cai no 429.
        response = api_client.post(
            url_login,
            {"email": "alice@example.com", "password": "SenhaForte!123"},
            format="json",
        )
        assert response.status_code == status.HTTP_429_TOO_MANY_REQUESTS


# ---------------------------------------------------------------------------
# Refresh
# ---------------------------------------------------------------------------


def _login_e_pega_tokens(api_client, url_login, email, password):
    response = api_client.post(
        url_login,
        {"email": email, "password": password},
        format="json",
    )
    assert response.status_code == status.HTTP_200_OK
    return response.data["access"], response.data["refresh"]


@pytest.mark.django_db
class TestCustomerRefresh:
    def test_refresh_happy_retorna_novo_access(
        self, api_client, url_login, url_refresh, customer_user
    ):
        _, refresh = _login_e_pega_tokens(
            api_client, url_login, "alice@example.com", "SenhaForte!123"
        )
        response = api_client.post(
            url_refresh, {"refresh": refresh}, format="json"
        )
        assert response.status_code == status.HTTP_200_OK
        assert "access" in response.data

    def test_refresh_apos_logout_retorna_401_blacklisted(
        self, api_client, url_login, url_refresh, url_logout, customer_user
    ):
        access, refresh = _login_e_pega_tokens(
            api_client, url_login, "alice@example.com", "SenhaForte!123"
        )
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
        logout_resp = api_client.post(
            url_logout, {"refresh": refresh}, format="json"
        )
        assert logout_resp.status_code == status.HTTP_205_RESET_CONTENT

        api_client.credentials()  # limpa Authorization
        response = api_client.post(
            url_refresh, {"refresh": refresh}, format="json"
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED


# ---------------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestCustomerLogout:
    def test_logout_happy_retorna_205(
        self, api_client, url_login, url_logout, customer_user
    ):
        access, refresh = _login_e_pega_tokens(
            api_client, url_login, "alice@example.com", "SenhaForte!123"
        )
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
        response = api_client.post(
            url_logout, {"refresh": refresh}, format="json"
        )
        assert response.status_code == status.HTTP_205_RESET_CONTENT

    def test_logout_sem_refresh_retorna_400(
        self, api_client, url_login, url_logout, customer_user
    ):
        access, _ = _login_e_pega_tokens(
            api_client, url_login, "alice@example.com", "SenhaForte!123"
        )
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
        response = api_client.post(url_logout, {}, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_logout_idempotente_para_refresh_ja_blacklisted(
        self, api_client, url_login, url_logout, customer_user
    ):
        """
        P-1B: o logout é IDEMPOTENTE. Se o refresh já está blacklisted (ou
        de outra forma "equivalente a gone"), o segundo logout ainda retorna
        205 — porque o objetivo (sessão revogada) já está cumprido. Frontend
        pode chamar logout em retry sem receber 401 espúrio.
        """
        access, refresh = _login_e_pega_tokens(
            api_client, url_login, "alice@example.com", "SenhaForte!123"
        )
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
        # Primeiro logout: 205.
        first = api_client.post(
            url_logout, {"refresh": refresh}, format="json"
        )
        assert first.status_code == status.HTTP_205_RESET_CONTENT
        # Segundo logout com mesmo refresh: também 205 (idempotente).
        second = api_client.post(
            url_logout, {"refresh": refresh}, format="json"
        )
        assert second.status_code == status.HTTP_205_RESET_CONTENT

    def test_logout_com_refresh_de_outro_user_retorna_400(
        self, api_client, url_login, url_logout, customer_user
    ):
        """
        P-4: cross-user DoS. Se Alice loga e tenta blacklistar o refresh de
        Bob, recebe 400 genérico (sem revelar dono do token) e o refresh do
        Bob continua válido — verificamos via /refresh/ depois.
        """
        # User B ("bob"): obtém um refresh válido próprio.
        bob = User.objects.create_user(
            email="bob@example.com",
            password="SenhaForte!#999",
            nome_completo="Bob",
        )
        bob_refresh = _login_e_pega_tokens(
            api_client, url_login, "bob@example.com", "SenhaForte!#999"
        )[1]

        # User A ("alice"): loga e tenta blacklistar refresh de Bob.
        alice_access, _ = _login_e_pega_tokens(
            api_client, url_login, "alice@example.com", "SenhaForte!123"
        )
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {alice_access}")
        response = api_client.post(
            url_logout, {"refresh": bob_refresh}, format="json"
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert (
            response.data.get("error", {}).get("code") == "refresh_invalid"
        )

        # Refresh do Bob ainda funciona (não foi blacklistado pelo logout de Alice).
        api_client.credentials()  # limpa Authorization
        refresh_resp = api_client.post(
            reverse("users:customer-refresh"),
            {"refresh": bob_refresh},
            format="json",
        )
        assert refresh_resp.status_code == status.HTTP_200_OK
        assert "access" in refresh_resp.data
        # Sanity: usamos `bob` para evitar lint do unused fixture.
        assert bob.email == "bob@example.com"


# ---------------------------------------------------------------------------
# Me
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestCustomerMe:
    def test_me_anonimo_retorna_401(self, api_client, url_me):
        response = api_client.get(url_me)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_me_com_flag_false_retorna_200(
        self, api_client, url_login, url_me, customer_user
    ):
        access, _ = _login_e_pega_tokens(
            api_client, url_login, "alice@example.com", "SenhaForte!123"
        )
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
        response = api_client.get(url_me)
        assert response.status_code == status.HTTP_200_OK
        assert response.data["email"] == "alice@example.com"
        assert response.data["force_change_password"] is False

    def test_me_com_flag_true_ainda_retorna_200(
        self, api_client, url_login, url_me, customer_force_change
    ):
        """`/me/` é isento de IsCustomerPasswordCurrent — frontend precisa
        ler a flag para decidir o redirect."""
        access, _ = _login_e_pega_tokens(
            api_client, url_login, "bia@example.com", "TempPwd!#999"
        )
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
        response = api_client.get(url_me)
        assert response.status_code == status.HTTP_200_OK
        assert response.data["force_change_password"] is True


# ---------------------------------------------------------------------------
# Sanity admin endpoint não regrediu
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestAdminLoginNaoFoiAfetado:
    def test_admin_login_continua_funcionando(self, api_client, admin_user):
        url = reverse("users:admin-login")
        response = api_client.post(
            url,
            {"email": "admin@example.com", "password": "AdminPwd!#999"},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        assert "access" in response.data
        assert "refresh" in response.data
