"""Conciliação do ledger e quitação de repasse.

**O que está em jogo.** `relatorio_repasse` percorre a tabela `Repasse` e por
isso é cego ao pior caso: pedido pago cujo webhook nunca criou a linha. Esses
testes existem pra garantir que a auditoria enxerga o que o relatório não vê, e
que a quitação não deixa pagar duas vezes a mesma doação.
"""

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone

from clama.core.exceptions import PastoralAPIException
from clama.instituicoes.models import RepasseStatus
from clama.instituicoes.services.auditoria import TipoAchado, auditar
from clama.instituicoes.tests.factories import InstituicaoFactory, RepasseFactory
from clama.orders.models import PedidoStatus
from clama.orders.tests.factories import PedidoFactory

pytestmark = pytest.mark.django_db


def _tipos(achados) -> set:
    return {achado.tipo for achado in achados}


class TestOrfaos:
    """O achado que motiva o comando: dinheiro entrou, ledger não registrou."""

    def test_pedido_pago_sem_repasse_e_critico(self):
        instituicao = InstituicaoFactory()
        PedidoFactory(
            instituicao=instituicao,
            status=PedidoStatus.ENVIADA,
            valor_centavos=5000,
            eh_gratuito=False,
        )

        achados = auditar()

        (achado,) = [a for a in achados if a.tipo == TipoAchado.ORFAO]
        assert achado.gravidade == "CRÍTICO"
        assert achado.valor_em_jogo_centavos == 1000  # 20% de 5000

    @pytest.mark.parametrize(
        "status",
        [
            PedidoStatus.PAGO,
            PedidoStatus.GERANDO_ORACAO,
            PedidoStatus.ORACAO_GERADA,
            PedidoStatus.ENVIADA,
            PedidoStatus.AGUARDANDO_REENVIO,
            PedidoStatus.ERRO,
        ],
    )
    def test_todo_status_pos_pagamento_conta(self, status):
        """ERRO entra: o pagamento pode ter passado e a falha ser da geração."""
        instituicao = InstituicaoFactory()
        PedidoFactory(
            instituicao=instituicao,
            status=status,
            valor_centavos=5000,
            eh_gratuito=False,
        )

        assert TipoAchado.ORFAO in _tipos(auditar())

    @pytest.mark.parametrize(
        "status",
        [PedidoStatus.AGUARDANDO_PAGAMENTO, PedidoStatus.AGUARDANDO_CONFIRMACAO_EMAIL],
    )
    def test_pedido_que_ainda_espera_nao_e_orfao(self, status):
        instituicao = InstituicaoFactory()
        PedidoFactory(
            instituicao=instituicao,
            status=status,
            valor_centavos=5000,
            eh_gratuito=False,
        )

        assert auditar() == []

    def test_pedido_gratuito_nao_e_orfao(self):
        instituicao = InstituicaoFactory()
        PedidoFactory(
            instituicao=instituicao,
            status=PedidoStatus.ENVIADA,
            valor_centavos=0,
            eh_gratuito=True,
        )

        assert auditar() == []

    def test_pedido_sem_instituicao_nao_e_orfao(self):
        PedidoFactory(
            instituicao=None, status=PedidoStatus.ENVIADA, valor_centavos=5000
        )

        assert auditar() == []

    def test_pedido_com_repasse_nao_e_orfao(self):
        instituicao = InstituicaoFactory()
        pedido = PedidoFactory(
            instituicao=instituicao,
            status=PedidoStatus.ENVIADA,
            valor_centavos=5000,
            provider_payment_id="MP-1",
        )
        RepasseFactory(
            pedido=pedido,
            instituicao=instituicao,
            valor_base_centavos=5000,
            valor_centavos=1000,
        )

        assert auditar() == []


class TestOutrosAchados:
    def _pedido(self, instituicao, **overrides):
        campos = {
            "instituicao": instituicao,
            "status": PedidoStatus.ENVIADA,
            "valor_centavos": 5000,
            "provider_payment_id": "MP-1",
        }
        campos.update(overrides)
        return PedidoFactory(**campos)

    def test_calculo_fora_do_percentual_e_critico(self):
        instituicao = InstituicaoFactory()
        RepasseFactory(
            pedido=self._pedido(instituicao),
            instituicao=instituicao,
            valor_base_centavos=5000,
            percentual=20,
            valor_centavos=4000,  # deveria ser 1000
        )

        (achado,) = [a for a in auditar() if a.tipo == TipoAchado.CALCULO_ERRADO]
        assert achado.gravidade == "CRÍTICO"
        assert achado.valor_em_jogo_centavos == 3000

    def test_repasse_de_pedido_nao_pago_e_critico(self):
        instituicao = InstituicaoFactory()
        RepasseFactory(
            pedido=self._pedido(instituicao, status=PedidoStatus.AGUARDANDO_PAGAMENTO),
            instituicao=instituicao,
            valor_base_centavos=5000,
            valor_centavos=1000,
        )

        (achado,) = [a for a in auditar() if a.tipo == TipoAchado.PEDIDO_NAO_PAGO]
        assert achado.gravidade == "CRÍTICO"

    def test_divergencia_de_base_e_so_atencao(self):
        """Pedido convertido em gratuito depois do repasse: ledger certo, ruído esperado."""
        instituicao = InstituicaoFactory()
        pedido = self._pedido(instituicao, status=PedidoStatus.PAGO)
        RepasseFactory(
            pedido=pedido,
            instituicao=instituicao,
            valor_base_centavos=5000,
            valor_centavos=1000,
        )
        pedido.marcar_como_gratuito()

        achados = [a for a in auditar() if a.tipo == TipoAchado.DIVERGENCIA_DE_BASE]
        assert achados and achados[0].gravidade == "ATENÇÃO"

    def test_sem_id_de_pagamento_e_atencao(self):
        instituicao = InstituicaoFactory()
        RepasseFactory(
            pedido=self._pedido(instituicao, provider_payment_id=None),
            instituicao=instituicao,
            valor_base_centavos=5000,
            valor_centavos=1000,
        )

        (achado,) = [a for a in auditar() if a.tipo == TipoAchado.SEM_ID_DE_PAGAMENTO]
        assert achado.gravidade == "ATENÇÃO"

    def test_ledger_saudavel_nao_gera_achado(self):
        instituicao = InstituicaoFactory()
        RepasseFactory(
            pedido=self._pedido(instituicao),
            instituicao=instituicao,
            valor_base_centavos=5000,
            percentual=20,
            valor_centavos=1000,
        )

        assert auditar() == []

    def test_filtra_por_instituicao(self):
        alvo, outra = InstituicaoFactory(), InstituicaoFactory()
        PedidoFactory(
            instituicao=outra, status=PedidoStatus.ENVIADA, valor_centavos=5000
        )

        assert auditar(alvo) == []
        assert len(auditar(outra)) == 1


class TestComandoAuditar:
    def test_falha_quando_ha_achado_critico(self):
        instituicao = InstituicaoFactory()
        PedidoFactory(
            instituicao=instituicao, status=PedidoStatus.ENVIADA, valor_centavos=5000
        )

        with pytest.raises(CommandError, match="crítico"):
            call_command("auditar_repasses")

    def test_ledger_limpo_passa(self, capsys):
        InstituicaoFactory()

        call_command("auditar_repasses")

        assert "Ledger consistente" in capsys.readouterr().out

    def test_grava_csv_dos_achados(self, tmp_path):
        instituicao = InstituicaoFactory()
        PedidoFactory(
            instituicao=instituicao, status=PedidoStatus.ENVIADA, valor_centavos=5000
        )
        saida = tmp_path / "achados.csv"

        with pytest.raises(CommandError):
            call_command("auditar_repasses", f"--csv={saida}")

        texto = saida.read_text(encoding="utf-8-sig")
        assert "orfao" in texto
        assert "CRÍTICO" in texto


class TestQuitacao:
    def _repasse(self, instituicao=None):
        instituicao = instituicao or InstituicaoFactory(nome="Casa de Apoio")
        return RepasseFactory(
            instituicao=instituicao,
            pedido=PedidoFactory(
                instituicao=instituicao,
                status=PedidoStatus.ENVIADA,
                valor_centavos=5000,
                provider_payment_id="MP-1",
            ),
            valor_base_centavos=5000,
            valor_centavos=1000,
        )

    def test_nasce_pendente(self):
        assert self._repasse().pendente

    def test_marcar_como_transferido_grava_comprovante(self):
        repasse = self._repasse()

        repasse.marcar_como_transferido("E123-PIX")

        repasse.refresh_from_db()
        assert repasse.status == RepasseStatus.TRANSFERIDO
        assert repasse.comprovante == "E123-PIX"
        assert repasse.transferido_em is not None
        assert not repasse.pendente

    def test_recusa_quitar_duas_vezes(self):
        """Pagar o mesmo repasse duas vezes é o erro caro que isso previne."""
        repasse = self._repasse()
        repasse.marcar_como_transferido("E123-PIX")

        with pytest.raises(PastoralAPIException, match="já foi transferido"):
            repasse.marcar_como_transferido("E999-OUTRO")

    def test_comando_simula_por_padrao(self, capsys):
        repasse = self._repasse()

        call_command("marcar_repasse_transferido", "--instituicao=Casa de Apoio")

        repasse.refresh_from_db()
        assert repasse.status == RepasseStatus.REGISTRADO
        assert "SIMULAÇÃO" in capsys.readouterr().out

    def test_comando_exige_comprovante_para_confirmar(self):
        self._repasse()

        with pytest.raises(CommandError, match="comprovante"):
            call_command(
                "marcar_repasse_transferido",
                "--instituicao=Casa de Apoio",
                "--confirmar",
            )

    def test_comando_quita_com_confirmar(self):
        repasse = self._repasse()

        call_command(
            "marcar_repasse_transferido",
            "--instituicao=Casa de Apoio",
            "--comprovante=E123-PIX",
            "--confirmar",
        )

        repasse.refresh_from_db()
        assert repasse.status == RepasseStatus.TRANSFERIDO
        assert repasse.comprovante == "E123-PIX"

    def test_nao_requita_o_ja_transferido(self, capsys):
        repasse = self._repasse()
        repasse.marcar_como_transferido("E123-PIX")

        call_command(
            "marcar_repasse_transferido",
            "--instituicao=Casa de Apoio",
            "--comprovante=E999",
            "--confirmar",
        )

        repasse.refresh_from_db()
        assert repasse.comprovante == "E123-PIX"  # intacto
        assert "Nenhum repasse pendente" in capsys.readouterr().out


class TestRelatorioSomentePendentes:
    def test_recorta_o_que_falta_pagar(self, tmp_path):
        """O fechamento mensal precisa disso, senão reemite doação já quitada."""
        instituicao = InstituicaoFactory(nome="Casa de Apoio")
        pedido_a = PedidoFactory(nome="Maria Silva", instituicao=instituicao)
        pedido_b = PedidoFactory(nome="João Lima", instituicao=instituicao)
        pago = RepasseFactory(
            instituicao=instituicao,
            pedido=pedido_a,
            valor_base_centavos=5000,
            valor_centavos=1000,
        )
        RepasseFactory(
            instituicao=instituicao,
            pedido=pedido_b,
            valor_base_centavos=3000,
            valor_centavos=600,
        )
        pago.marcar_como_transferido("E123")
        saida = tmp_path / "pendentes.csv"

        call_command(
            "relatorio_repasse",
            "--instituicao=Casa de Apoio",
            "--somente-pendentes",
            f"--saida={saida}",
        )

        texto = saida.read_text(encoding="utf-8-sig")
        assert "João L." in texto
        assert "Maria S." not in texto
        assert "TOTAL (1 doação)" in texto

    def test_sem_a_flag_traz_tudo(self, tmp_path):
        instituicao = InstituicaoFactory(nome="Casa de Apoio")
        pago = RepasseFactory(instituicao=instituicao, valor_centavos=1000)
        RepasseFactory(instituicao=instituicao, valor_centavos=600)
        pago.marcar_como_transferido("E123")
        saida = tmp_path / "tudo.csv"

        call_command(
            "relatorio_repasse", "--instituicao=Casa de Apoio", f"--saida={saida}"
        )

        assert "TOTAL (2 doações)" in saida.read_text(encoding="utf-8-sig")

    def test_auditoria_mostra_status_e_comprovante(self, tmp_path):
        instituicao = InstituicaoFactory(nome="Casa de Apoio")
        repasse = RepasseFactory(
            instituicao=instituicao,
            pedido=PedidoFactory(instituicao=instituicao, provider_payment_id="MP-1"),
            valor_base_centavos=5000,
            valor_centavos=1000,
        )
        repasse.marcar_como_transferido("E123-PIX", quando=timezone.now())
        saida = tmp_path / "auditoria.csv"

        call_command(
            "relatorio_repasse",
            "--instituicao=Casa de Apoio",
            "--auditoria",
            f"--saida={saida}",
        )

        texto = saida.read_text(encoding="utf-8-sig")
        assert "transferido" in texto
        assert "E123-PIX" in texto
