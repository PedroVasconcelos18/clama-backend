"""Relatório de repasse entregue à instituição parceira.

**O que estes testes protegem.** O relatório vira dinheiro combinado com um
terceiro — erro aqui é repasse cobrado a menor/maior, ou PII de doador vazando
pra fora do Clama. Três invariantes:

1. O valor vem do snapshot em `Repasse`, nunca de `Pedido.valor_centavos` —
   que `marcar_como_gratuito()` zera depois do pagamento confirmado.
2. O corte do período usa `Repasse.created_at` (confirmação do pagamento) com
   bordas inclusivas — doação de 31/08 23:59 entra no fechamento de agosto.
3. O padrão de identificação é abreviado; nome completo só sob flag explícita.
"""

import csv
from datetime import date, datetime, time, timedelta

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone

from clama.instituicoes.management.commands.relatorio_repasse import (
    CABECALHO_AUDITORIA,
    CABECALHO_CSV,
)
from clama.instituicoes.services.relatorio import (
    Identificacao,
    abreviar_nome,
    gerar_relatorio,
)
from clama.instituicoes.tests.factories import InstituicaoFactory, RepasseFactory
from clama.orders.models import PedidoStatus
from clama.orders.tests.factories import PedidoFactory

pytestmark = pytest.mark.django_db


def _repasse_em(instituicao, dia: datetime | date, **overrides):
    """Cria um repasse fixando `created_at` (auto_now_add ignora o kwarg)."""
    if isinstance(dia, date) and not isinstance(dia, datetime):
        dia = datetime.combine(dia, time(12, 0))
    repasse = RepasseFactory(instituicao=instituicao, **overrides)
    quando = timezone.make_aware(dia) if timezone.is_naive(dia) else dia
    type(repasse).objects.filter(pk=repasse.pk).update(created_at=quando)
    repasse.refresh_from_db()
    return repasse


def _linhas_do_csv(caminho) -> list[list[str]]:
    """Só as linhas de doação — pula cabeçalho, título e a linha de TOTAL."""
    with caminho.open(encoding="utf-8-sig") as arquivo:
        linhas = list(csv.reader(arquivo, delimiter=";"))
    return [
        linha
        for linha in linhas
        if len(linha) == len(CABECALHO_CSV)
        and linha[0] not in ("Doador",)
        and not linha[0].startswith("TOTAL")
    ]


class TestAbreviarNome:
    @pytest.mark.parametrize(
        ("entrada", "esperado"),
        [
            ("Maria Silva Santos", "Maria S."),
            ("Maria da Silva", "Maria S."),
            ("Maria", "Maria"),
            ("", "(sem nome)"),
            ("   ", "(sem nome)"),
            ("ana carolina souza", "ana S."),
        ],
    )
    def test_abrevia_pelo_ultimo_sobrenome(self, entrada, esperado):
        assert abreviar_nome(entrada) == esperado


class TestValores:
    def test_soma_o_snapshot_do_ledger_e_nao_o_pedido(self):
        """`marcar_como_gratuito` zera o pedido; o relatório não pode zerar junto."""
        instituicao = InstituicaoFactory()
        pedido = PedidoFactory(valor_centavos=5000)
        RepasseFactory(
            pedido=pedido,
            instituicao=instituicao,
            valor_base_centavos=5000,
            percentual=20,
            valor_centavos=1000,
        )
        pedido.marcar_como_gratuito()  # zera Pedido.valor_centavos

        relatorio = gerar_relatorio(instituicao)

        assert relatorio.total_doado_centavos == 5000
        assert relatorio.total_repasse_centavos == 1000

    def test_totaliza_multiplas_doacoes(self):
        instituicao = InstituicaoFactory()
        for base in (5000, 3000, 10000):
            RepasseFactory(
                instituicao=instituicao,
                valor_base_centavos=base,
                valor_centavos=base * 20 // 100,
            )

        relatorio = gerar_relatorio(instituicao)

        assert relatorio.quantidade == 3
        assert relatorio.total_doado_centavos == 18000
        assert relatorio.total_repasse_centavos == 3600

    def test_ignora_repasse_de_outra_instituicao(self):
        alvo, outra = InstituicaoFactory(), InstituicaoFactory()
        RepasseFactory(instituicao=alvo, valor_centavos=1000)
        RepasseFactory(instituicao=outra, valor_centavos=9999)

        relatorio = gerar_relatorio(alvo)

        assert relatorio.quantidade == 1
        assert relatorio.total_repasse_centavos == 1000

    def test_periodo_sem_repasse_zera_sem_estourar(self):
        relatorio = gerar_relatorio(InstituicaoFactory())

        assert relatorio.quantidade == 0
        assert relatorio.total_doado_centavos == 0
        assert relatorio.total_repasse_centavos == 0


class TestPeriodo:
    def test_bordas_sao_inclusivas(self):
        instituicao = InstituicaoFactory()
        _repasse_em(instituicao, datetime(2026, 8, 1, 0, 0), valor_centavos=100)
        _repasse_em(instituicao, datetime(2026, 8, 31, 23, 59), valor_centavos=200)
        _repasse_em(instituicao, datetime(2026, 7, 31, 23, 59), valor_centavos=999)
        _repasse_em(instituicao, datetime(2026, 9, 1, 0, 1), valor_centavos=888)

        relatorio = gerar_relatorio(
            instituicao, desde=date(2026, 8, 1), ate=date(2026, 8, 31)
        )

        assert relatorio.quantidade == 2
        assert relatorio.total_repasse_centavos == 300

    def test_ordena_por_data_da_confirmacao(self):
        instituicao = InstituicaoFactory()
        _repasse_em(instituicao, date(2026, 8, 20), valor_centavos=300)
        _repasse_em(instituicao, date(2026, 8, 5), valor_centavos=100)
        _repasse_em(instituicao, date(2026, 8, 12), valor_centavos=200)

        relatorio = gerar_relatorio(instituicao)

        assert [linha.valor_repasse_centavos for linha in relatorio.linhas] == [
            100,
            200,
            300,
        ]

    def test_sem_periodo_pega_tudo(self):
        instituicao = InstituicaoFactory()
        _repasse_em(instituicao, date(2025, 1, 1))
        _repasse_em(instituicao, date(2026, 8, 15))

        assert gerar_relatorio(instituicao).quantidade == 2


class TestIdentificacao:
    def test_abreviado_e_o_padrao(self):
        instituicao = InstituicaoFactory()
        RepasseFactory(
            instituicao=instituicao, pedido=PedidoFactory(nome="Maria Silva Santos")
        )

        (linha,) = gerar_relatorio(instituicao).linhas

        assert linha.doador == "Maria S."

    def test_completo_expoe_o_nome_inteiro(self):
        instituicao = InstituicaoFactory()
        RepasseFactory(
            instituicao=instituicao, pedido=PedidoFactory(nome="Maria Silva Santos")
        )

        (linha,) = gerar_relatorio(
            instituicao, identificacao=Identificacao.COMPLETO
        ).linhas

        assert linha.doador == "Maria Silva Santos"

    def test_anonimo_nao_carrega_nenhum_pedaco_do_nome(self):
        instituicao = InstituicaoFactory()
        RepasseFactory(
            instituicao=instituicao, pedido=PedidoFactory(nome="Maria Silva Santos")
        )

        (linha,) = gerar_relatorio(
            instituicao, identificacao=Identificacao.ANONIMO
        ).linhas

        assert "Maria" not in linha.doador
        assert "Silva" not in linha.doador
        assert linha.doador == linha.referencia

    def test_nenhum_modo_vaza_email_telefone_ou_o_pedido_de_oracao(self):
        instituicao = InstituicaoFactory()
        pedido = PedidoFactory(
            nome="Maria Silva",
            email="maria@exemplo.com",
            telefone="+5511999998888",
            pedido_oracao="Reze pela saúde da minha mãe",
        )
        RepasseFactory(instituicao=instituicao, pedido=pedido)

        for modo in Identificacao:
            (linha,) = gerar_relatorio(instituicao, identificacao=modo).linhas
            texto = " ".join(str(valor) for valor in vars(linha).values())
            assert "maria@exemplo.com" not in texto
            assert "999998888" not in texto
            assert "saúde da minha mãe" not in texto


class TestComando:
    def test_gera_csv_com_totais(self, tmp_path, capsys):
        instituicao = InstituicaoFactory(nome="Casa de Apoio")
        _repasse_em(
            instituicao,
            date(2026, 8, 12),
            pedido=PedidoFactory(nome="Maria Silva Santos"),
            valor_base_centavos=5000,
            valor_centavos=1000,
        )
        _repasse_em(
            instituicao,
            date(2026, 8, 14),
            pedido=PedidoFactory(nome="João Pereira Lima"),
            valor_base_centavos=3000,
            valor_centavos=600,
        )
        saida = tmp_path / "relatorio.csv"

        call_command(
            "relatorio_repasse",
            "--instituicao=Casa de Apoio",
            "--mes=2026-08",
            f"--saida={saida}",
        )

        with saida.open(encoding="utf-8-sig") as arquivo:
            linhas = list(csv.reader(arquivo, delimiter=";"))
        conteudo = [celula for linha in linhas for celula in linha]
        assert "Maria S." in conteudo
        assert "João L." in conteudo
        assert "Maria Silva Santos" not in conteudo
        total = next(
            linha for linha in linhas if linha and linha[0].startswith("TOTAL")
        )
        assert total[3] == "80,00"  # 5000 + 3000 centavos
        assert total[5] == "16,00"  # 1000 + 600 centavos
        assert "R$ 16,00" in capsys.readouterr().out

    def test_mes_recorta_o_fechamento(self, tmp_path):
        instituicao = InstituicaoFactory(nome="Casa de Apoio")
        _repasse_em(
            instituicao,
            date(2026, 8, 15),
            valor_base_centavos=5000,
            valor_centavos=1000,
        )
        _repasse_em(
            instituicao,
            date(2026, 9, 2),
            valor_base_centavos=25000,
            valor_centavos=5000,
        )
        saida = tmp_path / "agosto.csv"

        call_command(
            "relatorio_repasse",
            "--instituicao=Casa de Apoio",
            "--mes=2026-08",
            f"--saida={saida}",
        )

        linhas = _linhas_do_csv(saida)
        assert [linha[2] for linha in linhas] == ["15/08/2026"]
        assert [linha[5] for linha in linhas] == ["10,00"]

    def test_periodo_vazio_nao_grava_arquivo(self, tmp_path, capsys):
        InstituicaoFactory(nome="Casa de Apoio")
        saida = tmp_path / "vazio.csv"

        call_command(
            "relatorio_repasse",
            "--instituicao=Casa de Apoio",
            "--mes=2026-08",
            f"--saida={saida}",
        )

        assert not saida.exists()
        assert "Nenhum repasse" in capsys.readouterr().out

    def test_resolve_instituicao_por_uuid(self, tmp_path):
        instituicao = InstituicaoFactory(nome="Casa de Apoio")
        _repasse_em(instituicao, date(2026, 8, 10), valor_centavos=1000)
        saida = tmp_path / "por-uuid.csv"

        call_command(
            "relatorio_repasse",
            f"--instituicao={instituicao.id}",
            f"--saida={saida}",
        )

        assert saida.exists()

    def test_nome_ambiguo_falha_em_vez_de_escolher(self):
        InstituicaoFactory(nome="Casa de Apoio Norte")
        InstituicaoFactory(nome="Casa de Apoio Sul")

        with pytest.raises(CommandError, match="mais de uma instituição"):
            call_command("relatorio_repasse", "--instituicao=Casa de Apoio")

    def test_instituicao_inexistente_lista_as_cadastradas(self):
        InstituicaoFactory(nome="Casa de Apoio")

        with pytest.raises(CommandError, match="Casa de Apoio"):
            call_command("relatorio_repasse", "--instituicao=Lar São José")

    def test_mes_com_desde_ou_ate_e_recusado(self):
        InstituicaoFactory(nome="Casa de Apoio")

        with pytest.raises(CommandError, match="não os dois"):
            call_command(
                "relatorio_repasse",
                "--instituicao=Casa de Apoio",
                "--mes=2026-08",
                "--desde=2026-08-01",
            )

    def test_desde_posterior_a_ate_e_recusado(self):
        InstituicaoFactory(nome="Casa de Apoio")

        with pytest.raises(CommandError, match="posterior"):
            call_command(
                "relatorio_repasse",
                "--instituicao=Casa de Apoio",
                "--desde=2026-08-31",
                "--ate=2026-08-01",
            )

    def test_data_em_formato_invalido_e_recusada(self):
        InstituicaoFactory(nome="Casa de Apoio")

        with pytest.raises(CommandError, match="inválida"):
            call_command(
                "relatorio_repasse",
                "--instituicao=Casa de Apoio",
                "--desde=31-08-2026",
            )

    def test_dezembro_vira_janeiro_sem_estourar(self, tmp_path):
        instituicao = InstituicaoFactory(nome="Casa de Apoio")
        _repasse_em(
            instituicao,
            datetime(2026, 12, 31, 23, 30),
            valor_base_centavos=5000,
            valor_centavos=1000,
        )
        _repasse_em(
            instituicao,
            datetime(2027, 1, 1, 0, 30),
            valor_base_centavos=25000,
            valor_centavos=5000,
        )
        saida = tmp_path / "dezembro.csv"

        call_command(
            "relatorio_repasse",
            "--instituicao=Casa de Apoio",
            "--mes=2026-12",
            f"--saida={saida}",
        )

        linhas = _linhas_do_csv(saida)
        assert [linha[2] for linha in linhas] == ["31/12/2026"]
        assert [linha[5] for linha in linhas] == ["10,00"]

    def test_identificacao_completa_avisa_sobre_a_politica(self, tmp_path, capsys):
        instituicao = InstituicaoFactory(nome="Casa de Apoio")
        _repasse_em(
            instituicao,
            date(2026, 8, 10),
            pedido=PedidoFactory(nome="Maria Silva Santos"),
        )
        saida = tmp_path / "completo.csv"

        call_command(
            "relatorio_repasse",
            "--instituicao=Casa de Apoio",
            "--identificacao=completo",
            f"--saida={saida}",
        )

        assert "Maria Silva Santos" in saida.read_text(encoding="utf-8-sig")
        assert "Política de Privacidade" in capsys.readouterr().out

    def test_uma_doacao_sai_no_singular_e_periodo_por_extenso(self, tmp_path):
        """Documento vai pra fora do Clama — 'TOTAL (1 doações)' não pode sair."""
        instituicao = InstituicaoFactory(nome="Casa de Apoio")
        _repasse_em(instituicao, date(2026, 8, 10), valor_centavos=1000)
        saida = tmp_path / "singular.csv"

        call_command(
            "relatorio_repasse",
            "--instituicao=Casa de Apoio",
            "--mes=2026-08",
            f"--saida={saida}",
        )

        texto = saida.read_text(encoding="utf-8-sig")
        assert "TOTAL (1 doação)" in texto
        assert "doações" not in texto
        assert "Período: 01/08/2026 a 31/08/2026" in texto

    def test_sem_periodo_o_csv_diz_desde_o_inicio(self, tmp_path):
        instituicao = InstituicaoFactory(nome="Casa de Apoio")
        _repasse_em(instituicao, date(2026, 8, 10), valor_centavos=1000)
        saida = tmp_path / "tudo.csv"

        call_command(
            "relatorio_repasse", "--instituicao=Casa de Apoio", f"--saida={saida}"
        )

        assert "Período: desde o início" in saida.read_text(encoding="utf-8-sig")

    def test_apenas_resumo_nao_grava_arquivo(self, tmp_path, capsys):
        instituicao = InstituicaoFactory(nome="Casa de Apoio")
        _repasse_em(instituicao, date(2026, 8, 10), valor_centavos=1000)
        saida = tmp_path / "nao-deve-existir.csv"

        call_command(
            "relatorio_repasse",
            "--instituicao=Casa de Apoio",
            "--apenas-resumo",
            f"--saida={saida}",
        )

        assert not saida.exists()
        assert "R$ 10,00" in capsys.readouterr().out


class TestAuditoria:
    """Conciliação interna: amarra cada linha do ledger ao dinheiro no gateway."""

    def _pedido_pago(self, **overrides):
        campos = {
            "nome": "Maria Silva Santos",
            "email": "maria@exemplo.com",
            "valor_centavos": 5000,
            "status": PedidoStatus.ENVIADA,
            "provider_payment_id": "MP-123456789",
        }
        campos.update(overrides)
        return PedidoFactory(**campos)

    def test_traz_email_e_id_do_pagamento(self):
        instituicao = InstituicaoFactory()
        RepasseFactory(instituicao=instituicao, pedido=self._pedido_pago())

        (linha,) = gerar_relatorio(instituicao, auditoria=True).linhas

        assert linha.email == "maria@exemplo.com"
        assert linha.provider_payment_id == "MP-123456789"
        assert linha.status_pedido == PedidoStatus.ENVIADA
        assert linha.doador == "Maria Silva Santos"

    def test_sem_auditoria_os_campos_ficam_nulos(self):
        """Defesa em profundidade: nem um bug de coluna vaza e-mail pra instituição."""
        instituicao = InstituicaoFactory()
        RepasseFactory(instituicao=instituicao, pedido=self._pedido_pago())

        (linha,) = gerar_relatorio(instituicao).linhas

        assert linha.email is None
        assert linha.provider_payment_id is None
        assert linha.status_pedido is None

    def test_divergencia_quando_pedido_foi_zerado_depois(self):
        instituicao = InstituicaoFactory()
        pedido = self._pedido_pago(valor_centavos=5000, status=PedidoStatus.PAGO)
        RepasseFactory(
            pedido=pedido,
            instituicao=instituicao,
            valor_base_centavos=5000,
            valor_centavos=1000,
        )
        pedido.marcar_como_gratuito()

        (linha,) = gerar_relatorio(instituicao, auditoria=True).linhas

        assert linha.divergencia
        assert "5000" in linha.divergencia

    def test_sem_divergencia_quando_bate(self):
        instituicao = InstituicaoFactory()
        RepasseFactory(
            instituicao=instituicao,
            pedido=self._pedido_pago(valor_centavos=5000),
            valor_base_centavos=5000,
        )

        (linha,) = gerar_relatorio(instituicao, auditoria=True).linhas

        assert linha.divergencia == ""

    def test_csv_de_auditoria_tem_as_colunas_de_conciliacao(self, tmp_path):
        instituicao = InstituicaoFactory(nome="Casa de Apoio")
        _repasse_em(
            instituicao,
            date(2026, 8, 12),
            pedido=self._pedido_pago(),
            valor_base_centavos=5000,
            valor_centavos=1000,
        )
        saida = tmp_path / "auditoria.csv"

        call_command(
            "relatorio_repasse",
            "--instituicao=Casa de Apoio",
            "--auditoria",
            f"--saida={saida}",
        )

        texto = saida.read_text(encoding="utf-8-sig")
        assert "maria@exemplo.com" in texto
        assert "MP-123456789" in texto
        assert "Maria Silva Santos" in texto
        assert "USO INTERNO" in texto
        for coluna in CABECALHO_AUDITORIA:
            assert coluna in texto

    def test_csv_da_instituicao_nunca_leva_email(self, tmp_path):
        """A invariante que mais importa: os dois arquivos não podem se confundir."""
        instituicao = InstituicaoFactory(nome="Casa de Apoio")
        _repasse_em(instituicao, date(2026, 8, 12), pedido=self._pedido_pago())
        saida = tmp_path / "instituicao.csv"

        call_command(
            "relatorio_repasse", "--instituicao=Casa de Apoio", f"--saida={saida}"
        )

        texto = saida.read_text(encoding="utf-8-sig")
        assert "maria@exemplo.com" not in texto
        assert "MP-123456789" not in texto
        assert "Maria Silva Santos" not in texto
        assert "Maria S." in texto

    def test_avisa_quando_falta_id_de_pagamento(self, tmp_path, capsys):
        instituicao = InstituicaoFactory(nome="Casa de Apoio")
        _repasse_em(
            instituicao,
            date(2026, 8, 12),
            pedido=self._pedido_pago(provider_payment_id=None),
        )

        call_command(
            "relatorio_repasse",
            "--instituicao=Casa de Apoio",
            "--auditoria",
            "--apenas-resumo",
        )

        saida = capsys.readouterr().out
        assert "sem id de pagamento no gateway" in saida

    def test_avisa_que_o_arquivo_e_interno(self, tmp_path, capsys):
        instituicao = InstituicaoFactory(nome="Casa de Apoio")
        _repasse_em(instituicao, date(2026, 8, 12), pedido=self._pedido_pago())
        saida = tmp_path / "auditoria.csv"

        call_command(
            "relatorio_repasse",
            "--instituicao=Casa de Apoio",
            "--auditoria",
            f"--saida={saida}",
        )

        assert "Não entregar à instituição" in capsys.readouterr().out

    def test_nome_padrao_do_arquivo_marca_que_e_interno(self, tmp_path, monkeypatch):
        instituicao = InstituicaoFactory(nome="Casa de Apoio")
        _repasse_em(instituicao, date(2026, 8, 12), pedido=self._pedido_pago())
        monkeypatch.chdir(tmp_path)

        call_command("relatorio_repasse", "--instituicao=Casa de Apoio", "--auditoria")

        gerados = [caminho.name for caminho in tmp_path.glob("*.csv")]
        assert any("auditoria-INTERNA" in nome for nome in gerados), gerados


def test_repasse_de_hoje_entra_no_fechamento_do_mes_corrente():
    """Guarda contra fuso: `created_at` UTC não pode empurrar a doação pro dia seguinte."""
    instituicao = InstituicaoFactory()
    agora = timezone.localtime()
    RepasseFactory(instituicao=instituicao, valor_centavos=1000)

    relatorio = gerar_relatorio(
        instituicao,
        desde=agora.date(),
        ate=agora.date(),
    )

    assert relatorio.quantidade == 1
    assert relatorio.linhas[0].data == agora.date()
    assert relatorio.linhas[0].data != (agora + timedelta(days=1)).date()
