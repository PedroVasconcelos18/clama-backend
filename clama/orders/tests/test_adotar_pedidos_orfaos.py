"""Backfill que liga pedido órfão à conta dona do e-mail.

**Por que o comando existe.** `Pedido.user` só é preenchido por
`provisionar_conta_do_doador`, chamado de um lugar só: o webhook de pagamento.
Pedido gratuito custa R$ 0,00, não gera cobrança, não gera webhook — nunca
passa por lá. Nada adota órfão depois. O pedido aparece no admin com o e-mail
certo e some da conta de quem o fez.

**Por que o vínculo é em Python e não em query.** `Pedido.email` é
`EncryptedEmailField`: o banco guarda cifra. `email__iexact` devolve zero
mesmo com o valor igual — sem erro, sem aviso. Foi o que me levou a escrever
uma correção na listagem que era código morto.
"""

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command

from clama.orders.models import CanalEntrega, Pedido, PedidoStatus
from clama.plans.tests.factories import PlanFactory

pytestmark = pytest.mark.django_db

User = get_user_model()


@pytest.fixture
def plano(db):
    return PlanFactory(ativo=True, valor_centavos=2000)


@pytest.fixture
def dona(db):
    return User.objects.create_user(
        email="pedro@clama.me",
        password="Senha-Forte-12345!",
        nome_completo="Pedro Henrique",
    )


def _pedido(plano, **overrides):
    campos = dict(
        nome="Pedro Henrique",
        email="pedro@clama.me",
        telefone="+5511999998888",
        cpf_cnpj="11144477735",
        plano=plano,
        valor_centavos=0,
        canal_entrega=CanalEntrega.EMAIL,
        status=PedidoStatus.ENVIADA,
        user=None,
    )
    campos.update(overrides)
    return Pedido.objects.create(**campos)


class TestVinculo:
    def test_orfao_e_vinculado_a_conta_do_email(self, plano, dona):
        pedido = _pedido(plano)

        call_command("adotar_pedidos_orfaos")

        pedido.refresh_from_db()
        assert pedido.user_id == dona.id

    def test_case_do_email_nao_impede_o_vinculo(self, plano, dona):
        pedido = _pedido(plano, email="PEDRO@Clama.me")

        call_command("adotar_pedidos_orfaos")

        pedido.refresh_from_db()
        assert pedido.user_id == dona.id

    def test_orfao_sem_conta_correspondente_continua_orfao(self, plano, dona):
        pedido = _pedido(plano, email="ninguem@exemplo.com")

        call_command("adotar_pedidos_orfaos")

        pedido.refresh_from_db()
        assert pedido.user_id is None

    def test_pedido_ja_vinculado_nao_e_tocado(self, plano, dona):
        outra = User.objects.create_user(
            email="outra@clama.me",
            password="Senha-Forte-12345!",
            nome_completo="Outra",
        )
        pedido = _pedido(plano, user=outra, email="pedro@clama.me")

        call_command("adotar_pedidos_orfaos")

        pedido.refresh_from_db()
        # Continua da outra conta: o comando só alcança `user__isnull=True`.
        assert pedido.user_id == outra.id


class TestDryRun:
    def test_dry_run_nao_grava(self, plano, dona):
        pedido = _pedido(plano)

        call_command("adotar_pedidos_orfaos", "--dry-run")

        pedido.refresh_from_db()
        assert pedido.user_id is None

    def test_dry_run_seguido_de_execucao_real_vincula(self, plano, dona):
        pedido = _pedido(plano)

        call_command("adotar_pedidos_orfaos", "--dry-run")
        call_command("adotar_pedidos_orfaos")

        pedido.refresh_from_db()
        assert pedido.user_id == dona.id


class TestIdempotencia:
    def test_rodar_duas_vezes_nao_muda_nada(self, plano, dona):
        pedido = _pedido(plano)

        call_command("adotar_pedidos_orfaos")
        call_command("adotar_pedidos_orfaos")

        pedido.refresh_from_db()
        assert pedido.user_id == dona.id
        assert Pedido.objects.filter(user__isnull=True).count() == 0
