"""
Testes do endpoint POST /api/customer/auth/change-password/ (G2.a).

- Happy: usuário com flag true zera a flag e a nova senha funciona.
- Happy: usuário com flag false consegue trocar normalmente.
- Senha atual errada → 400 pastoral.
- Atomicidade: a operação roda dentro de `transaction.atomic()` e usa
  `select_for_update` na row do User.
"""

from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
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
def url_change_password():
    return reverse("users:customer-change-password")


def _login(api_client, email, password):
    response = api_client.post(
        reverse("users:customer-login"),
        {"email": email, "password": password},
        format="json",
    )
    assert response.status_code == status.HTTP_200_OK, response.data
    return response.data["access"]


@pytest.mark.django_db
class TestChangePasswordHappyForceChange:
    """Cenário típico do G1: User criado pela saga com flag true."""

    def test_aceita_temp_e_zera_flag(
        self, api_client, url_change_password
    ):
        user = User.objects.create_user(
            email="bia@example.com",
            password="TempPwd!#999",
            nome_completo="Bia Souza",
            force_change_password=True,
        )
        access = _login(api_client, "bia@example.com", "TempPwd!#999")
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")

        response = api_client.post(
            url_change_password,
            {"senha_atual": "TempPwd!#999", "nova_senha": "NovaSenhaForte!42"},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK

        user.refresh_from_db()
        assert user.force_change_password is False
        assert user.check_password("NovaSenhaForte!42") is True
        assert user.check_password("TempPwd!#999") is False


@pytest.mark.django_db
class TestChangePasswordHappyFlagFalse:
    def test_user_com_flag_false_troca_senha_normalmente(
        self, api_client, url_change_password
    ):
        user = User.objects.create_user(
            email="alice@example.com",
            password="SenhaForte!123",
            nome_completo="Alice",
        )
        access = _login(api_client, "alice@example.com", "SenhaForte!123")
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")

        response = api_client.post(
            url_change_password,
            {
                "senha_atual": "SenhaForte!123",
                "nova_senha": "OutraSenha!Forte9",
            },
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        user.refresh_from_db()
        assert user.force_change_password is False
        assert user.check_password("OutraSenha!Forte9") is True


@pytest.mark.django_db
class TestChangePasswordSenhaErrada:
    def test_senha_atual_errada_retorna_400(
        self, api_client, url_change_password
    ):
        """
        P-3: a verificação de `senha_atual` foi movida pra view (dentro do
        `transaction.atomic()` + `select_for_update`). Mantém o mesmo
        contrato pastoral: 400 com código `senha_atual_invalida`.
        """
        User.objects.create_user(
            email="alice@example.com",
            password="SenhaForte!123",
        )
        access = _login(api_client, "alice@example.com", "SenhaForte!123")
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")

        response = api_client.post(
            url_change_password,
            {"senha_atual": "errada-mesmo", "nova_senha": "NovaSenha!Forte42"},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert (
            response.data.get("error", {}).get("code") == "senha_atual_invalida"
        )
        assert (
            "A senha atual está incorreta"
            in response.data["error"]["pastoral_message"]
        )


@pytest.mark.django_db
class TestChangePasswordValidacaoNova:
    def test_senha_nova_curta_retorna_400(
        self, api_client, url_change_password
    ):
        User.objects.create_user(
            email="alice@example.com",
            password="SenhaForte!123",
        )
        access = _login(api_client, "alice@example.com", "SenhaForte!123")
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")

        response = api_client.post(
            url_change_password,
            {"senha_atual": "SenhaForte!123", "nova_senha": "abc"},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
class TestChangePasswordAnonimo:
    def test_anonimo_retorna_401(self, api_client, url_change_password):
        response = api_client.post(
            url_change_password,
            {"senha_atual": "x", "nova_senha": "NovaSenha!Forte42"},
            format="json",
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.django_db(transaction=True)
class TestChangePasswordTOCTOURace:
    """
    P-3: TOCTOU em `senha_atual`. A checagem precisa rodar DEPOIS do
    `select_for_update`, contra a row freshly-locked do banco. Antes,
    a validação rodava no serializer contra o cache do JWT auth — duas
    reqs concorrentes podiam passar a checagem em paralelo.

    Verificação principal: depois da troca, a senha antiga não funciona
    mais (i.e. a flag/senha está coerente; não houve "ganha o último").
    Usamos um spy para confirmar que `check_password` é chamado APÓS
    `select_for_update`. Race real com threads é flaky em SQLite, então
    o spy é o teste autoritativo aqui (best-effort).
    """

    def test_senha_atual_eh_checada_apos_select_for_update(
        self, api_client, url_change_password
    ):
        User.objects.create_user(
            email="alice@example.com",
            password="SenhaForte!123",
        )
        access = _login(api_client, "alice@example.com", "SenhaForte!123")
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")

        from django.db.models.query import QuerySet

        eventos = []

        original_sfu = QuerySet.select_for_update

        def _spy_sfu(self, *args, **kwargs):
            eventos.append("select_for_update")
            return original_sfu(self, *args, **kwargs)

        from clama_backend.users.models import User as UserModel

        original_cp = UserModel.check_password

        def _spy_cp(self, *args, **kwargs):
            eventos.append("check_password")
            return original_cp(self, *args, **kwargs)

        with patch.object(QuerySet, "select_for_update", _spy_sfu), patch.object(
            UserModel, "check_password", _spy_cp
        ):
            response = api_client.post(
                url_change_password,
                {
                    "senha_atual": "SenhaForte!123",
                    "nova_senha": "NovaSenha!Forte42",
                },
                format="json",
            )
        assert response.status_code == status.HTTP_200_OK
        # `check_password` deve ocorrer DEPOIS de `select_for_update`.
        # Filtramos só os eventos de interesse (pode haver outros calls).
        sfu_idx = eventos.index("select_for_update")
        cp_after_sfu = [
            i
            for i, e in enumerate(eventos)
            if e == "check_password" and i > sfu_idx
        ]
        assert cp_after_sfu, (
            f"check_password deveria ocorrer APÓS select_for_update; "
            f"eventos={eventos}"
        )


@pytest.mark.django_db
class TestChangePasswordInvalidaRefreshTokens:
    """
    P-6: após troca de senha, todos os refresh tokens do usuário são
    blacklistados — incluindo o da própria sessão e os de outros
    dispositivos. Assim, sessões "esquecidas" não sobrevivem a uma troca
    de senha forçada.
    """

    def test_refresh_de_sessao_paralela_eh_invalidado_apos_troca(
        self, api_client, url_change_password
    ):
        User.objects.create_user(
            email="alice@example.com",
            password="SenhaForte!123",
        )
        # Sessão 1: primeira login.
        login1 = api_client.post(
            reverse("users:customer-login"),
            {"email": "alice@example.com", "password": "SenhaForte!123"},
            format="json",
        )
        assert login1.status_code == status.HTTP_200_OK
        access1 = login1.data["access"]
        refresh1 = login1.data["refresh"]

        # Sessão 2: segunda login (outro dispositivo) — refresh diferente.
        login2 = api_client.post(
            reverse("users:customer-login"),
            {"email": "alice@example.com", "password": "SenhaForte!123"},
            format="json",
        )
        assert login2.status_code == status.HTTP_200_OK
        refresh2 = login2.data["refresh"]
        assert refresh1 != refresh2

        # Troca senha pela sessão 1.
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {access1}")
        response = api_client.post(
            url_change_password,
            {
                "senha_atual": "SenhaForte!123",
                "nova_senha": "NovaSenha!Forte42",
            },
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK

        # Sessão 2 tenta refresh — deve falhar (blacklisted).
        api_client.credentials()
        refresh_resp = api_client.post(
            reverse("users:customer-refresh"),
            {"refresh": refresh2},
            format="json",
        )
        assert refresh_resp.status_code == status.HTTP_401_UNAUTHORIZED

        # E sessão 1 também: o próprio refresh dela foi invalidado.
        refresh_resp1 = api_client.post(
            reverse("users:customer-refresh"),
            {"refresh": refresh1},
            format="json",
        )
        assert refresh_resp1.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.django_db
class TestChangePasswordAtomicSelectForUpdate:
    """
    Frozen — "atomic + select_for_update no User row".
    Verificamos que a view usa `select_for_update` patchando o `QuerySet`
    e contando chamadas. Se o método nunca for chamado, a frase do frozen
    não é cumprida.
    """

    def test_view_invoca_select_for_update_no_user(
        self, api_client, url_change_password
    ):
        User.objects.create_user(
            email="alice@example.com",
            password="SenhaForte!123",
        )
        access = _login(api_client, "alice@example.com", "SenhaForte!123")
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")

        from django.db.models.query import QuerySet

        original = QuerySet.select_for_update
        chamadas = {"n": 0}

        def _spy(self, *args, **kwargs):
            chamadas["n"] += 1
            return original(self, *args, **kwargs)

        with patch.object(QuerySet, "select_for_update", _spy):
            response = api_client.post(
                url_change_password,
                {
                    "senha_atual": "SenhaForte!123",
                    "nova_senha": "NovaSenha!Forte42",
                },
                format="json",
            )
        assert response.status_code == status.HTTP_200_OK
        assert chamadas["n"] >= 1, (
            "CustomerChangePasswordView deve usar select_for_update "
            "para serializar reqs concorrentes (frozen line)."
        )
