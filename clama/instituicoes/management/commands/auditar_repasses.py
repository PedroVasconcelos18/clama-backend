"""
Concilia o ledger de repasse com os pedidos.

Usage:
    python manage.py auditar_repasses
    python manage.py auditar_repasses --instituicao "Renais" --csv auditoria.csv

Somente leitura — não corrige nada. Sai com código 1 se houver achado crítico,
pra poder virar checagem agendada.
"""

import csv
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from clama.core.money import centavos_to_reais_str
from clama.instituicoes.models import Instituicao
from clama.instituicoes.services.auditoria import Achado, TipoAchado, auditar

CABECALHO_CSV = [
    "Gravidade",
    "Tipo",
    "Instituição",
    "ID do pedido",
    "Detalhe",
    "Valor em jogo (R$)",
]

EXPLICACAO = {
    TipoAchado.ORFAO: (
        "Pedido pago com instituição escolhida que nunca gerou linha no ledger. "
        "O repasse é devido e não aparece em relatório nenhum."
    ),
    TipoAchado.PEDIDO_NAO_PAGO: (
        "Repasse registrado para pedido que ainda aguarda pagamento — cobrança "
        "sem dinheiro correspondente."
    ),
    TipoAchado.CALCULO_ERRADO: (
        "O valor gravado não é o percentual do valor base. Ledger adulterado ou "
        "bug no cálculo."
    ),
    TipoAchado.DIVERGENCIA_DE_BASE: (
        "O pedido mudou de valor depois do repasse (ex.: convertido em gratuito). "
        "O ledger está certo; é só ruído esperado."
    ),
    TipoAchado.SEM_ID_DE_PAGAMENTO: (
        "Sem o id do Mercado Pago não dá pra bater a linha contra o extrato."
    ),
}


class Command(BaseCommand):
    help = "Concilia o ledger de repasse com os pedidos (somente leitura)."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--instituicao",
            help="Restringe a uma instituição (nome ou parte dele). Default: todas.",
        )
        parser.add_argument("--csv", help="Grava os achados em CSV neste caminho.")

    def handle(self, *args, **options) -> None:
        instituicao = None
        if options["instituicao"]:
            instituicao = self._resolver_instituicao(options["instituicao"])

        achados = auditar(instituicao)
        alvo = instituicao.nome if instituicao else "todas as instituições"

        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING(f"AUDITORIA DE REPASSE — {alvo}"))
        self.stdout.write("")

        if not achados:
            self.stdout.write(
                self.style.SUCCESS(
                    "Ledger consistente: nenhum pedido pago sem repasse, nenhum "
                    "cálculo errado, nenhum repasse sem pagamento."
                )
            )
            return

        self._imprimir(achados)
        if options["csv"]:
            destino = Path(options["csv"])
            self._gravar_csv(achados, destino)
            self.stdout.write(self.style.SUCCESS(f"\nCSV: {destino.resolve()}"))

        criticos = [a for a in achados if a.gravidade == "CRÍTICO"]
        if criticos:
            em_jogo = sum(a.valor_em_jogo_centavos for a in criticos)
            raise CommandError(
                f"{len(criticos)} achado(s) crítico(s), "
                f"{centavos_to_reais_str(em_jogo)} em jogo."
            )

    def _resolver_instituicao(self, termo: str) -> Instituicao:
        candidatas = list(Instituicao.objects.filter(nome__icontains=termo))
        if not candidatas:
            raise CommandError(f"Nenhuma instituição casa com {termo!r}.")
        if len(candidatas) > 1:
            nomes = ", ".join(f"{c.nome!r}" for c in candidatas)
            raise CommandError(f"{termo!r} casa com mais de uma: {nomes}.")
        return candidatas[0]

    def _imprimir(self, achados: list[Achado]) -> None:
        por_tipo: dict[TipoAchado, list[Achado]] = {}
        for achado in achados:
            por_tipo.setdefault(achado.tipo, []).append(achado)

        for tipo, grupo in por_tipo.items():
            estilo = (
                self.style.ERROR
                if grupo[0].gravidade == "CRÍTICO"
                else self.style.WARNING
            )
            self.stdout.write(
                estilo(f"[{grupo[0].gravidade}] {tipo} — {len(grupo)} ocorrência(s)")
            )
            self.stdout.write(f"  {EXPLICACAO[tipo]}")
            for achado in grupo:
                self.stdout.write(f"    pedido {achado.pedido_id}: {achado.detalhe}")
            self.stdout.write("")

        em_jogo = sum(a.valor_em_jogo_centavos for a in achados)
        if em_jogo:
            self.stdout.write(
                self.style.ERROR(f"Total em jogo: {centavos_to_reais_str(em_jogo)}")
            )

    def _gravar_csv(self, achados: list[Achado], destino: Path) -> None:
        destino.parent.mkdir(parents=True, exist_ok=True)
        with destino.open("w", newline="", encoding="utf-8-sig") as arquivo:
            escritor = csv.writer(arquivo, delimiter=";")
            escritor.writerow(CABECALHO_CSV)
            for achado in achados:
                escritor.writerow(
                    [
                        achado.gravidade,
                        achado.tipo,
                        achado.instituicao,
                        achado.pedido_id,
                        achado.detalhe,
                        f"{achado.valor_em_jogo_centavos // 100},"
                        f"{achado.valor_em_jogo_centavos % 100:02d}",
                    ]
                )
