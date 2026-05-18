"""
Testes do endpoint `POST /api/customer/auth/forgot-password/`.

Cobre o fluxo "Esqueci minha senha":
- E-mail cadastrado → gera senha temp, seta force_change_password, envia e-mail.
- Resposta SEMPRE genérica (anti-enumeração): e-mail inexistente, admin,
  inativo e cadastrado retornam o mesmo 200 + mesma mensagem.
- A senha antiga deixa de funcionar; a temp do e-mail loga e cai no
  fluxo de troca obrigatória (force_change_password=True).
- Validação de formato de e-mail.

Throttling está DESABILITADO em `config.settings.test` (ver
`REST_FRAMEWORK.DEFAULT_THROTTLE_CLASSES = []`), então o limite 3/h não é
exercido aqui — fica coberto por inspeção da config + teste manual.
"""

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import check_password
from django.core import mail
from django.urls import reverse
from rest_framework import status as drf_status
from rest_framework.test import APIClient

from clama.core.pastoral_messages import MSG_CUSTOMER_FORGOT_PASSWORD_ENVIADO

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
    )


@pytest.fixture
def customer_force_change(db):
    """Conta freemium que nunca trocou a senha (force_change ainda True)."""
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


@pytest.fixture
def inactive_user(db):
    u = User.objects.create_user(
        email="inactive@example.com",
        password=CUSTOMER_PASSWORD,
        nome_completo="Inativo",
    )
    u.is_active = False
    u.save(update_fields=["is_active"])
    return u


def _forgot(client, email):
    return client.post(
        reverse("customers:forgot-password"),
        {"email": email},
        format="json",
    )


@pytest.mark.django_db
class TestForgotPasswordHappyPath:
    def test_email_cadastrado_gera_temp_e_envia_email(
        self, api_client, customer
    ):
        response = _forgot(api_client, customer.email)

        assert response.status_code == drf_status.HTTP_200_OK
        assert response.data["detail"] == MSG_CUSTOMER_FORGOT_PASSWORD_ENVIADO

        # Um e-mail foi enviado para o customer.
        assert len(mail.outbox) == 1
        sent = mail.outbox[0]
        assert sent.to == [customer.email]
        assert "senha" in sent.subject.lower()

        # A senha antiga não funciona mais; force_change_password ligado.
        customer.refresh_from_db()
        assert not check_password(CUSTOMER_PASSWORD, customer.password)
        assert customer.force_change_password is True

    def test_temp_password_do_email_funciona_no_login_e_exige_troca(
        self, api_client, customer
    ):
        _forgot(api_client, customer.email)

        # Extrai a senha temporária do corpo texto do e-mail.
        body = mail.outbox[0].body
        # Linha: "Senha temporária: XXXXXXXXXXXXXX"
        linha = next(
            l for l in body.splitlines() if "Senha temporária:" in l
        )
        senha_temp = linha.split("Senha temporária:")[1].strip()
        assert len(senha_temp) == 14

        login = api_client.post(
            reverse("customers:login"),
            {"email": customer.email, "password": senha_temp},
            format="json",
        )
        assert login.status_code == drf_status.HTTP_200_OK
        assert login.data["user"]["force_change_password"] is True

    def test_email_case_insensitive(self, api_client, customer):
        response = _forgot(api_client, customer.email.upper())
        assert response.status_code == drf_status.HTTP_200_OK
        assert len(mail.outbox) == 1
        customer.refresh_from_db()
        assert customer.force_change_password is True

    def test_conta_freemium_force_change_pode_resetar_de_novo(
        self, api_client, customer_force_change
    ):
        """Quem perdeu o e-mail original do freemium consegue novo reset."""
        senha_antiga_hash = customer_force_change.password

        response = _forgot(api_client, customer_force_change.email)

        assert response.status_code == drf_status.HTTP_200_OK
        assert len(mail.outbox) == 1
        customer_force_change.refresh_from_db()
        # Senha mudou (nova temp) e flag continua exigindo troca.
        assert customer_force_change.password != senha_antiga_hash
        assert customer_force_change.force_change_password is True


@pytest.mark.django_db
class TestForgotPasswordAntiEnumeration:
    def test_email_inexistente_retorna_mesma_resposta_generica(
        self, api_client
    ):
        response = _forgot(api_client, "naoexiste@example.com")
        assert response.status_code == drf_status.HTTP_200_OK
        assert response.data["detail"] == MSG_CUSTOMER_FORGOT_PASSWORD_ENVIADO
        assert len(mail.outbox) == 0

    def test_admin_nao_recebe_email_e_resposta_identica(
        self, api_client, admin_user
    ):
        response = _forgot(api_client, admin_user.email)
        assert response.status_code == drf_status.HTTP_200_OK
        assert response.data["detail"] == MSG_CUSTOMER_FORGOT_PASSWORD_ENVIADO
        assert len(mail.outbox) == 0
        admin_user.refresh_from_db()
        # Senha do admin intacta.
        assert check_password(CUSTOMER_PASSWORD, admin_user.password)
        assert admin_user.force_change_password is False

    def test_conta_inativa_nao_recebe_email_e_resposta_identica(
        self, api_client, inactive_user
    ):
        response = _forgot(api_client, inactive_user.email)
        assert response.status_code == drf_status.HTTP_200_OK
        assert response.data["detail"] == MSG_CUSTOMER_FORGOT_PASSWORD_ENVIADO
        assert len(mail.outbox) == 0
        inactive_user.refresh_from_db()
        assert check_password(CUSTOMER_PASSWORD, inactive_user.password)

    def test_resposta_existente_vs_inexistente_sao_byte_identicas(
        self, api_client, customer
    ):
        r_exist = _forgot(api_client, customer.email)
        r_unknown = _forgot(api_client, "ninguem@example.com")
        assert r_exist.status_code == r_unknown.status_code
        assert r_exist.data == r_unknown.data


@pytest.mark.django_db
class TestForgotPasswordValidation:
    def test_email_formato_invalido_retorna_400(self, api_client):
        response = _forgot(api_client, "isto-nao-eh-email")
        assert response.status_code == drf_status.HTTP_400_BAD_REQUEST
        assert len(mail.outbox) == 0

    def test_email_ausente_retorna_400(self, api_client):
        response = api_client.post(
            reverse("customers:forgot-password"), {}, format="json"
        )
        assert response.status_code == drf_status.HTTP_400_BAD_REQUEST
        assert len(mail.outbox) == 0
