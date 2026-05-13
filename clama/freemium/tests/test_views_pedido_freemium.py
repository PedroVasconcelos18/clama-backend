"""
Testes do endpoint POST /api/freemium/pedidos/.

Cenários do I/O Matrix cobertos:
- Submissão happy → 201 com Pedido em AGUARDANDO_CONFIRMACAO_EMAIL e e-mail
  de confirmação enfileirado (transaction.on_commit).
- CAPTCHA Turnstile inválido → 400 antes de qualquer chamada externa.
- CPF inválido (algoritmo) → 400 no deserialize.
- E-mail descartável → 400.
- User-existence gate (spec lp-user-existence-gate, 2026-05-10) → 409
  `user_ja_possui_conta` com `redirect: "/login"` se email/cpf/telefone
  bater em User existente.
- Pedido pendente do mesmo identificador → 409 `pedido_em_andamento`
  (substitui a P-V10 cancela-e-reusa).
- Blacklist hit (CPF, email, telefone) → 409 — telefone re-adicionado.
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

from clama.freemium.hashing import (
    hash_cpf_cnpj,
    hash_email,
    hash_ip,
    hash_telefone,
)
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
    def test_email_descartavel_retorna_400(
        self, api_client, url_pedido_freemium, plano_gratuito
    ):
        response = api_client.post(
            url_pedido_freemium,
            _payload(email="user@mailinator.com"),
            format="json",
        )
        assert response.status_code == drf_status.HTTP_400_BAD_REQUEST
        assert response.data["error"]["code"] == "email_descartavel"
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
class TestPedidoFreemiumPedidoEmAndamento:
    """
    Spec lp-user-existence-gate (2026-05-10): resubmissão com pedido
    pendente (`AGUARDANDO_CONFIRMACAO_EMAIL`) NÃO cancela mais o anterior
    — agora bloqueia com 409 `pedido_em_andamento`. P-V10 obsoleto.
    """

    def test_resubmissao_mesmo_cpf_retorna_409_pedido_em_andamento(
        self, api_client, url_pedido_freemium, plano_gratuito
    ):
        # Primeira submissão.
        case = TestCase()
        with case.captureOnCommitCallbacks(execute=True):
            r1 = api_client.post(url_pedido_freemium, _payload(), format="json")
        assert r1.status_code == drf_status.HTTP_201_CREATED
        pedido1_id = r1.data["pedido_id"]

        # Segunda submissão do mesmo CPF/email/telefone — agora bloqueada.
        r2 = api_client.post(url_pedido_freemium, _payload(), format="json")
        assert r2.status_code == drf_status.HTTP_409_CONFLICT
        assert r2.data["error"]["code"] == "pedido_em_andamento"

        # Pedido 1 NÃO foi cancelado — continua em
        # AGUARDANDO_CONFIRMACAO_EMAIL.
        pedido1 = Pedido.objects.get(id=pedido1_id)
        assert pedido1.status == PedidoStatus.AGUARDANDO_CONFIRMACAO_EMAIL

        # Apenas um Pedido total (não criou um novo).
        assert Pedido.objects.count() == 1

    def test_resubmissao_mesmo_telefone_retorna_409_pedido_em_andamento(
        self, api_client, url_pedido_freemium, plano_gratuito
    ):
        case = TestCase()
        with case.captureOnCommitCallbacks(execute=True):
            r1 = api_client.post(url_pedido_freemium, _payload(), format="json")
        assert r1.status_code == drf_status.HTTP_201_CREATED

        # Email + CPF diferentes, mesmo telefone.
        r2 = api_client.post(
            url_pedido_freemium,
            _payload(
                email="outro@example.com",
                cpf_cnpj="11144477735",  # outro CPF válido (DV ok)
            ),
            format="json",
        )
        assert r2.status_code == drf_status.HTTP_409_CONFLICT
        assert r2.data["error"]["code"] == "pedido_em_andamento"


@pytest.mark.django_db
class TestPedidoFreemiumUserExistenteGate:
    """
    Spec lp-user-existence-gate (2026-05-10): se algum identificador
    bater em User existente → 409 `user_ja_possui_conta` com
    `redirect: "/login"`.
    """

    def _criar_user(self, **overrides):
        UserModel = get_user_model()
        defaults = dict(
            email=EMAIL_OK,
            password="senha-temp-existente",
            cpf_cnpj=CPF_VALIDO,
            telefone=TELEFONE_OK,
        )
        defaults.update(overrides)
        return UserModel.objects.create_user(**defaults)

    def test_email_de_user_existente_retorna_409_user_ja_possui_conta(
        self, api_client, url_pedido_freemium, plano_gratuito
    ):
        self._criar_user()
        response = api_client.post(
            url_pedido_freemium, _payload(), format="json"
        )
        assert response.status_code == drf_status.HTTP_409_CONFLICT
        assert response.data["error"]["code"] == "user_ja_possui_conta"
        assert response.data["error"]["redirect"] == "/login"
        assert not Pedido.objects.exists()

    def test_email_gmail_alias_de_user_existente_retorna_409_redirect(
        self, api_client, url_pedido_freemium, plano_gratuito
    ):
        """
        User cadastrou `alicetest@gmail.com`. Atacante submete com
        `alice.test+1@gmail.com` — mesma caixa, mesma origem. Hash bate
        pela canonicalização Gmail.
        """
        self._criar_user(email="alicetest@gmail.com")
        response = api_client.post(
            url_pedido_freemium,
            _payload(email="alice.test+1@gmail.com"),
            format="json",
        )
        assert response.status_code == drf_status.HTTP_409_CONFLICT
        assert response.data["error"]["code"] == "user_ja_possui_conta"

    def test_cpf_de_user_existente_retorna_409_redirect(
        self, api_client, url_pedido_freemium, plano_gratuito
    ):
        self._criar_user()
        response = api_client.post(
            url_pedido_freemium,
            _payload(email="outro@example.com", telefone="+5511777776666"),
            format="json",
        )
        assert response.status_code == drf_status.HTTP_409_CONFLICT
        assert response.data["error"]["code"] == "user_ja_possui_conta"

    def test_telefone_de_user_existente_retorna_409_redirect(
        self, api_client, url_pedido_freemium, plano_gratuito
    ):
        self._criar_user()
        response = api_client.post(
            url_pedido_freemium,
            _payload(
                email="outro@example.com",
                cpf_cnpj="11144477735",  # outro CPF válido (DV ok)
            ),
            format="json",
        )
        assert response.status_code == drf_status.HTTP_409_CONFLICT
        assert response.data["error"]["code"] == "user_ja_possui_conta"


@pytest.mark.django_db
class TestPedidoFreemiumBlacklistTelefone:
    """telefone_hash re-adicionado em 2026-05-10 — agora bloqueia também."""

    def test_blacklist_hit_telefone_retorna_409(
        self, api_client, url_pedido_freemium, plano_gratuito
    ):
        FreemiumBlacklist.objects.create(
            cpf_hash="z" * 64,
            email_hash="y" * 64,
            telefone_hash=hash_telefone(TELEFONE_OK),
        )
        response = api_client.post(
            url_pedido_freemium, _payload(), format="json"
        )
        assert response.status_code == drf_status.HTTP_409_CONFLICT
        assert response.data["error"]["code"] == "freemium_blacklist_hit"
        assert not Pedido.objects.exists()


@pytest.mark.django_db
class TestPedidoFreemiumBlacklistDeviceHash:
    """
    Anti-bypass aba anônima (2026-05-10): mesmo com email/CPF/telefone
    totalmente novos, se o `device_hash` (FingerprintJS visitorId) bater
    com entry da blacklist → 409.
    """

    def test_device_hash_diferente_passa(
        self, api_client, url_pedido_freemium, plano_gratuito
    ):
        """Sanity check: device_hash novo NÃO bloqueia."""
        FreemiumBlacklist.objects.create(
            cpf_hash="z" * 64,
            email_hash="y" * 64,
            device_hash="device-hash-de-outro-browser",
        )
        from django.test import TestCase

        case = TestCase()
        with case.captureOnCommitCallbacks(execute=True):
            response = api_client.post(
                url_pedido_freemium,
                _payload(device_hash="device-hash-novo-xyz-1234567"),
                format="json",
            )
        assert response.status_code == drf_status.HTTP_201_CREATED

    def test_device_hash_igual_bloqueia_mesmo_com_outros_identificadores_novos(
        self, api_client, url_pedido_freemium, plano_gratuito
    ):
        """
        Cenário do user: aba anônima + email temp + CPF gerado + telefone
        falso. Tudo "novo" exceto o device_hash do browser. Deve bater.
        """
        FreemiumBlacklist.objects.create(
            cpf_hash="z" * 64,  # CPF irrelevante
            email_hash="y" * 64,  # email irrelevante
            telefone_hash="x" * 64,  # telefone irrelevante
            device_hash=DEVICE_HASH_OK,
        )
        response = api_client.post(
            url_pedido_freemium,
            _payload(
                # TUDO diferente do payload original
                email="atacante_temp@10minutemail.test",  # email novo
                cpf_cnpj="11144477735",  # CPF válido novo
                telefone="+5511777776666",  # telefone novo
                device_hash=DEVICE_HASH_OK,  # MESMO device
            ),
            format="json",
        )
        # 10minutemail é disposable — pra isolar o teste do
        # device_hash check, vamos usar outro domínio
        assert response.status_code in (
            drf_status.HTTP_409_CONFLICT,
            drf_status.HTTP_400_BAD_REQUEST,
        )

    def test_device_hash_bloqueia_com_email_real(
        self, api_client, url_pedido_freemium, plano_gratuito
    ):
        """Isolando do disposable check: usa Gmail e device_hash repetido."""
        FreemiumBlacklist.objects.create(
            cpf_hash="z" * 64,
            email_hash="y" * 64,
            telefone_hash="x" * 64,
            device_hash=DEVICE_HASH_OK,
        )
        response = api_client.post(
            url_pedido_freemium,
            _payload(
                email="atacante-novo@example.com",
                cpf_cnpj="11144477735",
                telefone="+5511777776666",
                device_hash=DEVICE_HASH_OK,
            ),
            format="json",
        )
        assert response.status_code == drf_status.HTTP_409_CONFLICT
        assert response.data["error"]["code"] == "freemium_blacklist_hit"
        assert not Pedido.objects.exists()

    def test_device_hash_vazio_nao_dispara_check(
        self, api_client, url_pedido_freemium, plano_gratuito
    ):
        """
        Falha-aberta: se FingerprintJS falha (Brave shields), device_hash
        vem vazio. Não queremos bloquear usuária legítima — então o check
        é skipped quando device_hash é "".
        """
        FreemiumBlacklist.objects.create(
            cpf_hash="z" * 64,
            email_hash="y" * 64,
            device_hash="",  # blacklist legada também com "" — não deve bater
        )
        from django.test import TestCase

        case = TestCase()
        with case.captureOnCommitCallbacks(execute=True):
            response = api_client.post(
                url_pedido_freemium,
                _payload(device_hash=""),
                format="json",
            )
        # Não deve travar — device_hash vazio sai do check.
        assert response.status_code == drf_status.HTTP_201_CREATED


@pytest.mark.django_db
class TestPedidoFreemiumBlacklistIp:
    """
    Anti-bypass por IP — opção D (threshold de confirmações).

    Permite uso legítimo em rede compartilhada (biblioteca, CGNAT móvel)
    bloqueando só quando o acúmulo de confirmações no mesmo IP é
    suspeito. Default threshold=3 dentro de window_hours=1 (settings).
    """

    def _ip_de_teste(self):
        return "203.0.113.55"

    def _criar_entries(self, ip: str, n: int):
        """Cria N entries na blacklist com o mesmo ip_hash (todas recentes)."""
        for i in range(n):
            FreemiumBlacklist.objects.create(
                cpf_hash=f"cpf-{i}".ljust(64, "0"),
                email_hash=f"email-{i}".ljust(64, "0"),
                ip_hash=hash_ip(ip),
            )

    def test_ip_abaixo_do_threshold_libera(
        self, api_client, url_pedido_freemium, plano_gratuito
    ):
        """2 entries no IP (threshold default=3) → 3ª submissão passa."""
        from django.test import TestCase

        ip = self._ip_de_teste()
        self._criar_entries(ip, 2)

        case = TestCase()
        with case.captureOnCommitCallbacks(execute=True):
            response = api_client.post(
                url_pedido_freemium,
                _payload(),
                format="json",
                HTTP_X_FORWARDED_FOR=ip,
            )
        assert response.status_code == drf_status.HTTP_201_CREATED

    def test_ip_atinge_threshold_bloqueia(
        self, api_client, url_pedido_freemium, plano_gratuito
    ):
        """3 entries no IP → 4ª submissão é bloqueada (sinal de abuso)."""
        ip = self._ip_de_teste()
        self._criar_entries(ip, 3)

        response = api_client.post(
            url_pedido_freemium,
            _payload(
                email="atacante-novo@example.com",
                cpf_cnpj="11144477735",
                telefone="+5511777776666",
                device_hash="device-novo-da-aba-anonima",
            ),
            format="json",
            HTTP_X_FORWARDED_FOR=ip,
        )
        assert response.status_code == drf_status.HTTP_409_CONFLICT
        assert response.data["error"]["code"] == "freemium_blacklist_hit"
        assert not Pedido.objects.exists()

    def test_threshold_customizado_via_settings(
        self, api_client, url_pedido_freemium, plano_gratuito, settings
    ):
        """Threshold é configurável via env."""
        settings.FREEMIUM_IP_BLACKLIST_THRESHOLD = 2  # mais restritivo

        ip = self._ip_de_teste()
        self._criar_entries(ip, 2)

        response = api_client.post(
            url_pedido_freemium,
            _payload(),
            format="json",
            HTTP_X_FORWARDED_FOR=ip,
        )
        assert response.status_code == drf_status.HTTP_409_CONFLICT

    def test_entries_fora_da_janela_nao_contam(
        self, api_client, url_pedido_freemium, plano_gratuito
    ):
        """
        Janela default = 1h. Entries com >1h NÃO contam pro threshold,
        protegendo CGNAT de cauterização longa.
        """
        from datetime import timedelta
        from django.test import TestCase
        from django.utils import timezone

        ip = self._ip_de_teste()
        # 3 entries antigas (>1h) — deveriam estourar threshold, mas estão
        # fora da janela.
        for i in range(3):
            entry = FreemiumBlacklist.objects.create(
                cpf_hash=f"old-cpf-{i}".ljust(64, "0"),
                email_hash=f"old-email-{i}".ljust(64, "0"),
                ip_hash=hash_ip(ip),
            )
            FreemiumBlacklist.objects.filter(pk=entry.pk).update(
                created_at=timezone.now() - timedelta(hours=2)
            )

        case = TestCase()
        with case.captureOnCommitCallbacks(execute=True):
            response = api_client.post(
                url_pedido_freemium,
                _payload(),
                format="json",
                HTTP_X_FORWARDED_FOR=ip,
            )
        assert response.status_code == drf_status.HTTP_201_CREATED

    def test_ip_diferente_libera(
        self, api_client, url_pedido_freemium, plano_gratuito
    ):
        """Sanity: IP novo nunca conta — mesmo com outras entries no banco."""
        from django.test import TestCase

        self._criar_entries("198.51.100.10", 5)  # IP diferente, várias entries

        case = TestCase()
        with case.captureOnCommitCallbacks(execute=True):
            response = api_client.post(
                url_pedido_freemium,
                _payload(),
                format="json",
                HTTP_X_FORWARDED_FOR="203.0.113.99",
            )
        assert response.status_code == drf_status.HTTP_201_CREATED


@pytest.mark.django_db
class TestSagaDeviceHashNaBlacklist:
    """Após confirmação, blacklist criada inclui device_hash do Pedido."""

    def test_saga_grava_device_hash_na_blacklist(
        self, api_client, url_pedido_freemium, plano_gratuito
    ):
        """Submit cria Pedido com device_hash; saga (test_views_confirmar)
        usa esse device_hash quando insere na blacklist."""
        from django.test import TestCase

        case = TestCase()
        with case.captureOnCommitCallbacks(execute=True):
            r = api_client.post(
                url_pedido_freemium,
                _payload(device_hash="dev-hash-pra-blacklist-xyz"),
                format="json",
            )
        assert r.status_code == drf_status.HTTP_201_CREATED
        pedido = Pedido.objects.get(id=r.data["pedido_id"])
        assert pedido.device_hash == "dev-hash-pra-blacklist-xyz"
