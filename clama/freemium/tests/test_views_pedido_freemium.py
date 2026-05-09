"""
Testes do endpoint POST /api/freemium/pedidos/ (pós-renegociação 2026-05-08).

Cenários do I/O Matrix cobertos:
- Submissão happy → 201 com Pedido em AGUARDANDO_CONFIRMACAO_EMAIL e e-mail
  de confirmação enfileirado (transaction.on_commit).
- CAPTCHA Turnstile inválido → 400 antes de qualquer chamada externa.
- CPF inválido (algoritmo) → 400 no deserialize.
- E-mail descartável → 400 antes de Infosimples.
- CPF inativo na Receita → 400.
- Infosimples down (após retries) → 503 + Sentry alert.
- Blacklist hit (CPF, email) → 409 — telefone fora pós-renegociação.
- Rate limit IP → 429 (não testado em DRF default em settings de teste,
  mas a estrutura de throttle é comprovada pelo scope `freemium_pedido_ip`).
- Pedido persistido com status correto, device_hash capturado, token
  de confirmação criado.
"""

from unittest.mock import patch

import pytest
import requests
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework import status as drf_status
from rest_framework.test import APIClient

from clama.freemium.hashing import hash_cpf_cnpj, hash_email
from clama.freemium.models import (
    FreemiumBlacklist,
    FreemiumConfirmationToken,
)
from clama.freemium.tests.factories import get_or_create_plano_gratuito
from clama.orders.models import CanalEntrega, Pedido, PedidoStatus

CPF_VALIDO = "24971563792"  # CPF com DV válido (alinhado com o de orders.tests)
EMAIL_OK = "alice@example.com"
TELEFONE_OK = "+5511999998888"
DEVICE_HASH_OK = "abcdef1234567890"  # >=10 chars
TURNSTILE_TOKEN_OK = "valid-cf-token-XXXX"

User = get_user_model()


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def url_pedido_freemium():
    return reverse("freemium-pedido-create")


@pytest.fixture
def plano_gratuito(db):
    return get_or_create_plano_gratuito()


def _payload(**overrides):
    base = {
        "nome": "Alice Maria",
        "email": EMAIL_OK,
        "telefone": TELEFONE_OK,
        "cpf_cnpj": CPF_VALIDO,
        "idade": 30,
        "sexo": "feminino",
        "pedido_oracao": "Por minha família.",
        "consent_aceito": True,
        "turnstile_token": TURNSTILE_TOKEN_OK,
        "device_hash": DEVICE_HASH_OK,
    }
    base.update(overrides)
    return base


@pytest.mark.django_db
class TestPedidoFreemiumHappy:
    def test_201_cria_pedido_em_aguardando_confirmacao_email_e_dispara_email_task(
        self,
        api_client,
        url_pedido_freemium,
        plano_gratuito,
    ):
        """Happy path: cria Pedido e dispara task de e-mail no commit."""
        case = TestCase()
        with patch(
            "clama.notifications.tasks.enviar_email_confirmacao_freemium_task.delay"
        ) as mock_email_task:
            with case.captureOnCommitCallbacks(execute=True):
                response = api_client.post(
                    url_pedido_freemium, _payload(), format="json"
                )

        assert response.status_code == drf_status.HTTP_201_CREATED, response.data
        assert "pedido_id" in response.data
        assert response.data["status"] == PedidoStatus.AGUARDANDO_CONFIRMACAO_EMAIL
        # Não deve retornar login_email — User ainda não existe.
        assert "login_email" not in response.data

        pedido = Pedido.objects.get(id=response.data["pedido_id"])
        assert pedido.eh_gratuito is True
        assert pedido.valor_centavos == 0
        assert pedido.plano_id == plano_gratuito.id
        assert pedido.status == PedidoStatus.AGUARDANDO_CONFIRMACAO_EMAIL
        assert pedido.canal_entrega == CanalEntrega.EMAIL
        # User ainda não existe
        assert pedido.user is None
        # Asaas não tocado
        assert pedido.asaas_charge_id == ""

        # Task de e-mail foi enfileirada
        mock_email_task.assert_called_once()
        args = mock_email_task.call_args[0]
        assert args[0] == str(pedido.id)
        # token é o segundo argumento
        assert isinstance(args[1], str) and len(args[1]) > 0


@pytest.mark.django_db
class TestPedidoFreemiumTurnstile:
    def test_captcha_turnstile_invalido_retorna_400(
        self, api_client, url_pedido_freemium, plano_gratuito, turnstile_invalido
    ):
        response = api_client.post(
            url_pedido_freemium, _payload(), format="json"
        )
        assert response.status_code == drf_status.HTTP_400_BAD_REQUEST
        assert response.data["error"]["code"] == "captcha_invalido"
        # Nada persistido
        assert not Pedido.objects.exists()
        assert not FreemiumConfirmationToken.objects.exists()

    def test_captcha_falha_de_rede_retorna_400(
        self, api_client, url_pedido_freemium, plano_gratuito
    ):
        """Falha permanente do Turnstile (rede esgotada) também 400 pastoral."""
        with patch(
            "clama.freemium.api.views.TurnstileClient.validate",
            side_effect=requests.RequestException("boom"),
        ):
            response = api_client.post(
                url_pedido_freemium, _payload(), format="json"
            )
        assert response.status_code == drf_status.HTTP_400_BAD_REQUEST
        assert response.data["error"]["code"] == "captcha_invalido"


@pytest.mark.django_db
class TestPedidoFreemiumValidacaoSerializer:
    def test_cpf_invalido_algoritmo_retorna_400(
        self, api_client, url_pedido_freemium, plano_gratuito
    ):
        response = api_client.post(
            url_pedido_freemium,
            _payload(cpf_cnpj="11111111111"),  # CPF rejeitado pelo algoritmo
            format="json",
        )
        assert response.status_code == drf_status.HTTP_400_BAD_REQUEST
        assert not Pedido.objects.exists()

    def test_telefone_fora_de_e164_retorna_400(
        self, api_client, url_pedido_freemium, plano_gratuito
    ):
        response = api_client.post(
            url_pedido_freemium, _payload(telefone="11999998888"), format="json"
        )
        assert response.status_code == drf_status.HTTP_400_BAD_REQUEST

    def test_consent_recusado_retorna_400(
        self, api_client, url_pedido_freemium, plano_gratuito
    ):
        response = api_client.post(
            url_pedido_freemium, _payload(consent_aceito=False), format="json"
        )
        assert response.status_code == drf_status.HTTP_400_BAD_REQUEST

    def test_pedido_oracao_acima_de_2000_chars_retorna_400(
        self, api_client, url_pedido_freemium, plano_gratuito
    ):
        response = api_client.post(
            url_pedido_freemium,
            _payload(pedido_oracao="x" * 2001),
            format="json",
        )
        assert response.status_code == drf_status.HTTP_400_BAD_REQUEST

    def test_device_hash_curto_aceita(
        self, api_client, url_pedido_freemium, plano_gratuito
    ):
        """
        P-V15 wave 2: device_hash agora é opcional (instrumentação only).
        Antes da P-V15, < 10 chars → 400. Agora aceita qualquer string,
        incluindo vazia / curta — frontend pode falhar no FingerprintJS
        (Brave shields, ad-blockers) e ainda assim concluir o pedido.
        """
        case = TestCase()
        with case.captureOnCommitCallbacks(execute=True):
            response = api_client.post(
                url_pedido_freemium,
                _payload(device_hash="curto"),
                format="json",
            )
        assert response.status_code == drf_status.HTTP_201_CREATED
        pedido = Pedido.objects.get(id=response.data["pedido_id"])
        assert pedido.device_hash == "curto"

    def test_turnstile_token_vazio_retorna_400(
        self, api_client, url_pedido_freemium, plano_gratuito
    ):
        response = api_client.post(
            url_pedido_freemium, _payload(turnstile_token=""), format="json"
        )
        assert response.status_code == drf_status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
class TestPedidoFreemiumEmailDescartavel:
    def test_email_descartavel_retorna_400_antes_de_infosimples(
        self, api_client, url_pedido_freemium, plano_gratuito
    ):
        # Garante que se Infosimples for chamado o teste falha — afirmação
        # negativa de "vem antes".
        with patch(
            "clama.freemium.api.views.InfosimplesClient.consultar_cpf_cnpj"
        ) as mock_infosimples:
            response = api_client.post(
                url_pedido_freemium,
                _payload(email="user@mailinator.com"),
                format="json",
            )

        assert response.status_code == drf_status.HTTP_400_BAD_REQUEST
        assert response.data["error"]["code"] == "email_descartavel"
        mock_infosimples.assert_not_called()
        assert not Pedido.objects.exists()


@pytest.mark.django_db
class TestPedidoFreemiumInfosimples:
    def test_cpf_inativo_retorna_400(
        self, api_client, url_pedido_freemium, plano_gratuito
    ):
        with patch(
            "clama.freemium.api.views.InfosimplesClient.consultar_cpf_cnpj",
            return_value={"status": "SUSPENSO", "nome": None},
        ):
            response = api_client.post(
                url_pedido_freemium, _payload(), format="json"
            )
        assert response.status_code == drf_status.HTTP_400_BAD_REQUEST
        assert response.data["error"]["code"] == "documento_inativo"
        assert not Pedido.objects.exists()

    def test_infosimples_down_retorna_503_e_alerta_sentry(
        self, api_client, url_pedido_freemium, plano_gratuito
    ):
        with patch(
            "clama.freemium.api.views.InfosimplesClient.consultar_cpf_cnpj",
            side_effect=requests.RequestException("network down"),
        ), patch("clama.freemium.api.views.sentry_sdk.capture_exception") as sentry:
            response = api_client.post(
                url_pedido_freemium, _payload(), format="json"
            )
        assert response.status_code == drf_status.HTTP_503_SERVICE_UNAVAILABLE
        assert response.data["error"]["code"] == "infosimples_indisponivel"
        sentry.assert_called_once()
        assert not Pedido.objects.exists()


@pytest.mark.django_db
class TestPedidoFreemiumBlacklist:
    def test_blacklist_hit_cpf_retorna_409(
        self, api_client, url_pedido_freemium, plano_gratuito
    ):
        FreemiumBlacklist.objects.create(
            cpf_hash=hash_cpf_cnpj(CPF_VALIDO),
            email_hash="z" * 64,
        )
        response = api_client.post(
            url_pedido_freemium, _payload(), format="json"
        )
        assert response.status_code == drf_status.HTTP_409_CONFLICT
        assert response.data["error"]["code"] == "freemium_blacklist_hit"
        assert FreemiumBlacklist.objects.count() == 1
        assert not Pedido.objects.exists()

    def test_blacklist_hit_email_retorna_409(
        self, api_client, url_pedido_freemium, plano_gratuito
    ):
        FreemiumBlacklist.objects.create(
            cpf_hash="z" * 64,
            email_hash=hash_email(EMAIL_OK),
        )
        response = api_client.post(
            url_pedido_freemium, _payload(), format="json"
        )
        assert response.status_code == drf_status.HTTP_409_CONFLICT
        assert not Pedido.objects.exists()


@pytest.mark.django_db
class TestPedidoFreemiumPersistencia:
    def test_pedido_persistido_com_status_aguardando_confirmacao_email(
        self, api_client, url_pedido_freemium, plano_gratuito
    ):
        case = TestCase()
        with case.captureOnCommitCallbacks(execute=True):
            response = api_client.post(
                url_pedido_freemium, _payload(), format="json"
            )
        assert response.status_code == drf_status.HTTP_201_CREATED
        pedido = Pedido.objects.get(id=response.data["pedido_id"])
        assert pedido.status == PedidoStatus.AGUARDANDO_CONFIRMACAO_EMAIL

    def test_pedido_persistido_com_device_hash_capturado(
        self, api_client, url_pedido_freemium, plano_gratuito
    ):
        case = TestCase()
        with case.captureOnCommitCallbacks(execute=True):
            response = api_client.post(
                url_pedido_freemium,
                _payload(device_hash="device-hash-particular-XYZ-1234"),
                format="json",
            )
        assert response.status_code == drf_status.HTTP_201_CREATED
        pedido = Pedido.objects.get(id=response.data["pedido_id"])
        assert pedido.device_hash == "device-hash-particular-XYZ-1234"

    def test_token_de_confirmacao_gerado_e_persistido(
        self, api_client, url_pedido_freemium, plano_gratuito
    ):
        case = TestCase()
        with case.captureOnCommitCallbacks(execute=True):
            response = api_client.post(
                url_pedido_freemium, _payload(), format="json"
            )
        pedido_id = response.data["pedido_id"]
        tokens = list(
            FreemiumConfirmationToken.objects.filter(pedido_id=pedido_id)
        )
        assert len(tokens) == 1
        token = tokens[0]
        assert token.used_at is None
        assert token.device_hash == DEVICE_HASH_OK
        assert len(token.token) > 0

    def test_email_task_enfileirada_em_on_commit(
        self, api_client, url_pedido_freemium, plano_gratuito
    ):
        """
        Confirma que o `enviar_email_confirmacao_freemium_task.delay` é
        chamado APÓS o commit (transaction.on_commit), não antes.
        """
        case = TestCase()
        with patch(
            "clama.notifications.tasks.enviar_email_confirmacao_freemium_task.delay"
        ) as mock_email_task:
            # Sem captureOnCommitCallbacks(execute=True) o callback NÃO roda
            # dentro do TestCase rolled-back transaction. Verificamos isso
            # invertido: dentro do `with` → não chamado; ao executar
            # callbacks → chamado.
            with case.captureOnCommitCallbacks(execute=False) as callbacks:
                response = api_client.post(
                    url_pedido_freemium, _payload(), format="json"
                )
                assert response.status_code == drf_status.HTTP_201_CREATED
                # Antes de executar os callbacks, .delay não deveria ter
                # sido chamada.
                mock_email_task.assert_not_called()

            # Executa manualmente os callbacks de on_commit.
            for cb in callbacks:
                cb()
            mock_email_task.assert_called_once()


@pytest.mark.django_db
class TestPedidoFreemiumDeviceHashOpcional:
    """P-V15 wave 2: device_hash agora é opcional no payload."""

    def test_device_hash_ausente_aceita_e_persiste_string_vazia(
        self, api_client, url_pedido_freemium, plano_gratuito
    ):
        payload = _payload()
        del payload["device_hash"]
        case = TestCase()
        with case.captureOnCommitCallbacks(execute=True):
            response = api_client.post(
                url_pedido_freemium, payload, format="json"
            )
        assert response.status_code == drf_status.HTTP_201_CREATED
        pedido = Pedido.objects.get(id=response.data["pedido_id"])
        assert pedido.device_hash == ""

    def test_device_hash_vazio_aceita_e_persiste_string_vazia(
        self, api_client, url_pedido_freemium, plano_gratuito
    ):
        case = TestCase()
        with case.captureOnCommitCallbacks(execute=True):
            response = api_client.post(
                url_pedido_freemium, _payload(device_hash=""), format="json"
            )
        assert response.status_code == drf_status.HTTP_201_CREATED
        pedido = Pedido.objects.get(id=response.data["pedido_id"])
        assert pedido.device_hash == ""


@pytest.mark.django_db
class TestPedidoFreemiumCancelaResubmissao:
    """
    P-V10 wave 2: pedidos AGUARDANDO_CONFIRMACAO_EMAIL anteriores do mesmo
    CPF/email são cancelados antes do novo insert (semântica "último submit
    ganha"). Evita N órfãos por CPF.
    """

    def test_resubmissao_cancela_pedido_pendente_anterior(
        self, api_client, url_pedido_freemium, plano_gratuito
    ):
        # Primeira submissão.
        case = TestCase()
        with case.captureOnCommitCallbacks(execute=True):
            r1 = api_client.post(url_pedido_freemium, _payload(), format="json")
        assert r1.status_code == drf_status.HTTP_201_CREATED
        pedido1_id = r1.data["pedido_id"]

        # Segunda submissão do mesmo CPF/email.
        with case.captureOnCommitCallbacks(execute=True):
            r2 = api_client.post(url_pedido_freemium, _payload(), format="json")
        assert r2.status_code == drf_status.HTTP_201_CREATED
        pedido2_id = r2.data["pedido_id"]
        assert pedido1_id != pedido2_id

        # Pedido 1 ficou cancelado (status ERRO + last_error).
        pedido1 = Pedido.objects.get(id=pedido1_id)
        assert pedido1.status == PedidoStatus.ERRO
        assert pedido1.last_error == "cancelado_por_resubmissao"

        # Pedido 2 está em AGUARDANDO_CONFIRMACAO_EMAIL.
        pedido2 = Pedido.objects.get(id=pedido2_id)
        assert pedido2.status == PedidoStatus.AGUARDANDO_CONFIRMACAO_EMAIL

        # Token do pedido 1 foi deletado (cleanup).
        assert not FreemiumConfirmationToken.objects.filter(
            pedido_id=pedido1_id
        ).exists()
        # Token do pedido 2 existe.
        assert FreemiumConfirmationToken.objects.filter(
            pedido_id=pedido2_id
        ).exists()
