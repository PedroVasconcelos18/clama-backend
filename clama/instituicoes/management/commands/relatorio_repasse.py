"""
Emite o relatório de repasse de uma instituição parceira.

Usage:
    python manage.py relatorio_repasse --instituicao "Casa de Apoio" --mes 2026-08
    python manage.py relatorio_repasse --instituicao <uuid> --desde 2026-08-01 --ate 2026-08-31

Em produção (Railway), rodar por dentro do container — nome do doador é
`EncryptedCharField` e só descriptografa via ORM com a `FIELD_ENCRYPTION_KEY`
do ambiente; SQL direto no banco devolve cifra:

    railway ssh --service web "python manage.py relatorio_repasse --instituicao X --mes 2026-08"
"""

import csv
import unicodedata
from datetime import date, datetime, timedelta
from pathlib import Path
from uuid import UUID

from django.core.management.base import BaseCommand, CommandError

from clama.core.money import centavos_to_reais_str
from clama.instituicoes.models import Instituicao
from clama.instituicoes.services.relatorio import (
    Identificacao,
    RelatorioRepasse,
    gerar_relatorio,
)

FORMATOS_DE_DATA = ("%Y-%m-%d", "%d/%m/%Y")
CABECALHO_CSV = [
    "Doador",
    "Referência do pedido",
    "Data da doação",
    "Valor doado (R$)",
    "Percentual de repasse",
    "Valor a receber (R$)",
]
# Conciliação interna: o que permite amarrar cada linha do ledger ao dinheiro
# que de fato entrou no Mercado Pago. Nunca vai no arquivo da instituição.
CABECALHO_AUDITORIA = [
    "Doador (nome completo)",
    "E-mail",
    "ID do pedido",
    "ID do pagamento no gateway",
    "Status do pedido",
    "Data do pedido",
    "Data da confirmação",
    "Valor no ledger (R$)",
    "Valor atual do pedido (R$)",
    "Percentual",
    "Repasse (R$)",
    "Status do repasse",
    "Transferido em",
    "Comprovante",
    "Divergência",
]


def _parse_data(valor: str, rotulo: str) -> date:
    for formato in FORMATOS_DE_DATA:
        try:
            return datetime.strptime(valor, formato).date()
        except ValueError:
            continue
    raise CommandError(f"{rotulo} inválida: {valor!r}. Use AAAA-MM-DD ou DD/MM/AAAA.")


def _parse_mes(valor: str) -> tuple[date, date]:
    """'2026-08' -> (2026-08-01, 2026-08-31). Bordas inclusivas."""
    try:
        primeiro = datetime.strptime(valor, "%Y-%m").date()
    except ValueError as erro:
        raise CommandError(f"--mes inválido: {valor!r}. Use AAAA-MM.") from erro
    if primeiro.month == 12:
        proximo = primeiro.replace(year=primeiro.year + 1, month=1)
    else:
        proximo = primeiro.replace(month=primeiro.month + 1)
    return primeiro, proximo - timedelta(days=1)


def _centavos_para_planilha(centavos: int) -> str:
    """'5000' -> '50,00' — sem 'R$', pra planilha pt-BR somar a coluna."""
    return f"{centavos // 100},{centavos % 100:02d}"


def _plural_doacao(quantidade: int) -> str:
    return "doação" if quantidade == 1 else "doações"


def _slug(texto: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return "-".join(sem_acento.lower().split()) or "instituicao"


class Command(BaseCommand):
    help = "Emite o relatório de repasse (20%) de uma instituição parceira em CSV."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--instituicao",
            required=True,
            help="Nome (ou parte dele) ou UUID da instituição.",
        )
        parser.add_argument("--mes", help="Atalho de período fechado: AAAA-MM.")
        parser.add_argument("--desde", help="Início do período (inclusivo).")
        parser.add_argument("--ate", help="Fim do período (inclusivo).")
        parser.add_argument(
            "--identificacao",
            choices=[opcao.value for opcao in Identificacao],
            default=Identificacao.ABREVIADO.value,
            help=(
                "abreviado: 'Maria S.' (padrão). anonimo: só a referência do pedido. "
                "completo: nome inteiro — exige atualizar a Política de Privacidade "
                "antes de entregar à instituição."
            ),
        )
        parser.add_argument(
            "--saida",
            help="Caminho do CSV. Default: relatorio-repasse-<instituicao>-<periodo>.csv",
        )
        parser.add_argument(
            "--auditoria",
            action="store_true",
            help=(
                "CSV interno de conciliação: nome completo, e-mail, id do pagamento "
                "no gateway, status e divergências. USO INTERNO — não entregar à "
                "instituição."
            ),
        )
        parser.add_argument(
            "--somente-pendentes",
            action="store_true",
            help="Só repasses ainda não transferidos — o recorte do fechamento mensal.",
        )
        parser.add_argument(
            "--apenas-resumo",
            action="store_true",
            help="Só imprime no terminal, não grava CSV.",
        )

    def handle(self, *args, **options) -> None:
        instituicao = self._resolver_instituicao(options["instituicao"])
        desde, ate = self._resolver_periodo(options)
        auditoria = options["auditoria"]
        # `gerar_relatorio` promove pra COMPLETO quando auditoria=True.
        identificacao = Identificacao(options["identificacao"])

        relatorio = gerar_relatorio(
            instituicao,
            desde=desde,
            ate=ate,
            identificacao=identificacao,
            auditoria=auditoria,
            somente_pendentes=options["somente_pendentes"],
        )
        self._imprimir_resumo(relatorio, identificacao, auditoria)

        if relatorio.quantidade == 0:
            self.stdout.write(
                self.style.WARNING("Nenhum repasse no período — CSV não gerado.")
            )
            return
        if options["apenas_resumo"]:
            return

        destino = Path(options["saida"] or self._nome_padrao(relatorio, auditoria))
        self._gravar_csv(relatorio, destino, auditoria)
        self.stdout.write(self.style.SUCCESS(f"\nCSV gravado em: {destino.resolve()}"))

    def _resolver_instituicao(self, termo: str) -> Instituicao:
        try:
            return Instituicao.objects.get(id=UUID(termo))
        except ValueError:
            pass  # não é UUID — segue por nome
        except Instituicao.DoesNotExist as erro:
            raise CommandError(f"Nenhuma instituição com o id {termo}.") from erro

        candidatas = list(Instituicao.objects.filter(nome__iexact=termo))
        if not candidatas:
            candidatas = list(Instituicao.objects.filter(nome__icontains=termo))
        if not candidatas:
            disponiveis = ", ".join(Instituicao.objects.values_list("nome", flat=True))
            raise CommandError(
                f"Nenhuma instituição casa com {termo!r}. Cadastradas: {disponiveis or '(nenhuma)'}"
            )
        if len(candidatas) > 1:
            nomes = ", ".join(f"{c.nome!r}" for c in candidatas)
            raise CommandError(
                f"{termo!r} casa com mais de uma instituição: {nomes}. Use o nome exato ou o UUID."
            )
        return candidatas[0]

    def _resolver_periodo(self, options) -> tuple[date | None, date | None]:
        if options["mes"] and (options["desde"] or options["ate"]):
            raise CommandError("Use --mes OU --desde/--ate, não os dois.")
        if options["mes"]:
            return _parse_mes(options["mes"])

        desde = _parse_data(options["desde"], "--desde") if options["desde"] else None
        ate = _parse_data(options["ate"], "--ate") if options["ate"] else None
        if desde and ate and desde > ate:
            raise CommandError(f"--desde ({desde}) é posterior a --ate ({ate}).")
        return desde, ate

    def _periodo_por_extenso(self, relatorio: RelatorioRepasse) -> str:
        if not (relatorio.desde or relatorio.ate):
            return "desde o início"
        inicio = relatorio.desde.strftime("%d/%m/%Y") if relatorio.desde else "o início"
        fim = relatorio.ate.strftime("%d/%m/%Y") if relatorio.ate else "hoje"
        return f"{inicio} a {fim}"

    def _nome_padrao(self, relatorio: RelatorioRepasse, auditoria: bool) -> str:
        periodo = "completo"
        if relatorio.desde or relatorio.ate:
            periodo = f"{relatorio.desde or 'inicio'}_a_{relatorio.ate or 'hoje'}"
        prefixo = "auditoria-INTERNA-repasse" if auditoria else "relatorio-repasse"
        return f"{prefixo}-{_slug(relatorio.instituicao.nome)}-{periodo}.csv"

    def _imprimir_resumo(
        self,
        relatorio: RelatorioRepasse,
        identificacao: Identificacao,
        auditoria: bool = False,
    ) -> None:
        periodo = self._periodo_por_extenso(relatorio)

        self.stdout.write("")
        self.stdout.write(
            self.style.MIGRATE_HEADING(
                f"RELATÓRIO DE REPASSE — {relatorio.instituicao.nome}"
            )
        )
        self.stdout.write(f"Período: {periodo}")
        self.stdout.write("")

        largura = max((len(linha.doador) for linha in relatorio.linhas), default=6)
        largura = max(largura, len("Doador"))
        self.stdout.write(
            f"{'Doador':<{largura}}  {'Data':<10}  {'Doação':>12}  {'Repasse':>12}"
        )
        for linha in relatorio.linhas:
            self.stdout.write(
                f"{linha.doador:<{largura}}  "
                f"{linha.data.strftime('%d/%m/%Y'):<10}  "
                f"{centavos_to_reais_str(linha.valor_doacao_centavos):>12}  "
                f"{centavos_to_reais_str(linha.valor_repasse_centavos):>12}"
            )
        self.stdout.write("─" * (largura + 40))
        self.stdout.write(
            self.style.SUCCESS(
                f"{f'TOTAL ({relatorio.quantidade})':<{largura}}  "
                f"{'':<10}  "
                f"{centavos_to_reais_str(relatorio.total_doado_centavos):>12}  "
                f"{centavos_to_reais_str(relatorio.total_repasse_centavos):>12}"
            )
        )

        divergentes = [linha for linha in relatorio.linhas if linha.divergencia]
        if divergentes:
            self.stdout.write("")
            self.stdout.write(
                self.style.ERROR(
                    f"{len(divergentes)} pedido(s) com valor divergente do ledger:"
                )
            )
            for linha in divergentes:
                self.stdout.write(f"  {linha.referencia}: {linha.divergencia}")

        sem_pagamento = [
            linha
            for linha in relatorio.linhas
            if auditoria and not linha.provider_payment_id
        ]
        if sem_pagamento:
            self.stdout.write("")
            self.stdout.write(
                self.style.WARNING(
                    f"{len(sem_pagamento)} repasse(s) sem id de pagamento no gateway — "
                    "não dá pra conciliar com o extrato do Mercado Pago:"
                )
            )
            for linha in sem_pagamento:
                self.stdout.write(f"  {linha.referencia} ({linha.data:%d/%m/%Y})")

        if auditoria:
            self.stdout.write("")
            self.stdout.write(
                self.style.WARNING(
                    "ARQUIVO INTERNO: contém nome completo, e-mail e id de pagamento. "
                    "Não entregar à instituição."
                )
            )
        elif identificacao is Identificacao.COMPLETO:
            self.stdout.write("")
            self.stdout.write(
                self.style.WARNING(
                    "ATENÇÃO: nome completo dos doadores. A Política de Privacidade "
                    "vigente não lista instituições parceiras como destinatárias de "
                    "dados pessoais — atualize a política antes de entregar."
                )
            )

    def _gravar_csv(
        self, relatorio: RelatorioRepasse, destino: Path, auditoria: bool = False
    ) -> None:
        destino.parent.mkdir(parents=True, exist_ok=True)
        titulo = (
            f"AUDITORIA INTERNA de repasse — {relatorio.instituicao.nome}"
            if auditoria
            else f"Relatório de repasse — {relatorio.instituicao.nome}"
        )
        # utf-8-sig + ';': Excel pt-BR abre com acento certo e coluna numérica.
        with destino.open("w", newline="", encoding="utf-8-sig") as arquivo:
            escritor = csv.writer(arquivo, delimiter=";")
            escritor.writerow([titulo])
            escritor.writerow([f"Período: {self._periodo_por_extenso(relatorio)}"])
            if auditoria:
                escritor.writerow(
                    ["USO INTERNO — contém dado pessoal. Não entregar à instituição."]
                )
            escritor.writerow([])

            if auditoria:
                self._escrever_linhas_auditoria(escritor, relatorio)
            else:
                self._escrever_linhas_instituicao(escritor, relatorio)

    def _escrever_linhas_instituicao(
        self, escritor, relatorio: RelatorioRepasse
    ) -> None:
        escritor.writerow(CABECALHO_CSV)
        for linha in relatorio.linhas:
            escritor.writerow(
                [
                    linha.doador,
                    linha.referencia,
                    linha.data.strftime("%d/%m/%Y"),
                    _centavos_para_planilha(linha.valor_doacao_centavos),
                    f"{linha.percentual}%",
                    _centavos_para_planilha(linha.valor_repasse_centavos),
                ]
            )
        escritor.writerow([])
        escritor.writerow(
            [
                f"TOTAL ({relatorio.quantidade} {_plural_doacao(relatorio.quantidade)})",
                "",
                "",
                _centavos_para_planilha(relatorio.total_doado_centavos),
                "",
                _centavos_para_planilha(relatorio.total_repasse_centavos),
            ]
        )

    def _escrever_linhas_auditoria(self, escritor, relatorio: RelatorioRepasse) -> None:
        escritor.writerow(CABECALHO_AUDITORIA)
        for linha in relatorio.linhas:
            escritor.writerow(
                [
                    linha.doador,
                    linha.email or "",
                    str(linha.pedido_id),
                    linha.provider_payment_id or "(sem id no gateway)",
                    linha.status_pedido or "",
                    linha.pedido_criado_em.strftime("%d/%m/%Y")
                    if linha.pedido_criado_em
                    else "",
                    linha.data.strftime("%d/%m/%Y"),
                    _centavos_para_planilha(linha.valor_doacao_centavos),
                    _centavos_para_planilha(linha.valor_pedido_atual_centavos or 0),
                    f"{linha.percentual}%",
                    _centavos_para_planilha(linha.valor_repasse_centavos),
                    linha.status_repasse or "",
                    linha.transferido_em.strftime("%d/%m/%Y")
                    if linha.transferido_em
                    else "",
                    linha.comprovante or "",
                    linha.divergencia,
                ]
            )
        escritor.writerow([])
        total = [""] * len(CABECALHO_AUDITORIA)
        total[0] = (
            f"TOTAL ({relatorio.quantidade} {_plural_doacao(relatorio.quantidade)})"
        )
        total[7] = _centavos_para_planilha(relatorio.total_doado_centavos)
        total[10] = _centavos_para_planilha(relatorio.total_repasse_centavos)
        escritor.writerow(total)
