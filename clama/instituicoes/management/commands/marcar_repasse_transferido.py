"""
Marca repasses como transferidos depois que o dinheiro sai pra instituição.

Usage:
    # simula (padrão): mostra o que mudaria, não grava nada
    python manage.py marcar_repasse_transferido --instituicao "Renais" --mes 2026-08

    # grava
    python manage.py marcar_repasse_transferido --instituicao "Renais" --mes 2026-08 \
        --comprovante "E1234567820260901..." --confirmar

Sem isso o ledger só sabe registrar dívida, nunca quitação — e todo fechamento
mensal reemite as mesmas doações já pagas.
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from clama.core.money import centavos_to_reais_str
from clama.instituicoes.management.commands.relatorio_repasse import (
    Command as RelatorioCommand,
)
from clama.instituicoes.models import Repasse, RepasseStatus
from clama.instituicoes.services.relatorio import _fim_do_dia, _inicio_do_dia


class Command(BaseCommand):
    help = "Marca repasses de uma instituição como transferidos (quitação)."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--instituicao", required=True, help="Nome ou UUID.")
        parser.add_argument("--mes", help="Período fechado: AAAA-MM.")
        parser.add_argument("--desde", help="Início (inclusivo).")
        parser.add_argument("--ate", help="Fim (inclusivo).")
        parser.add_argument(
            "--comprovante",
            default="",
            help="Referência da transferência (ex.: id ponta-a-ponta do Pix).",
        )
        parser.add_argument(
            "--confirmar",
            action="store_true",
            help="Grava. Sem esta flag o comando só simula.",
        )

    def handle(self, *args, **options) -> None:
        # Reusa a resolução de instituição e período do relatório — os dois
        # comandos têm que recortar exatamente o mesmo conjunto, senão você
        # quita um período diferente do que emitiu.
        auxiliar = RelatorioCommand()
        instituicao = auxiliar._resolver_instituicao(options["instituicao"])
        desde, ate = auxiliar._resolver_periodo(options)

        pendentes = Repasse.objects.filter(
            instituicao=instituicao, status=RepasseStatus.REGISTRADO
        )
        if desde is not None:
            pendentes = pendentes.filter(created_at__gte=_inicio_do_dia(desde))
        if ate is not None:
            pendentes = pendentes.filter(created_at__lte=_fim_do_dia(ate))
        pendentes = list(pendentes.order_by("created_at"))

        if not pendentes:
            self.stdout.write(
                self.style.WARNING(
                    f"Nenhum repasse pendente para {instituicao.nome} no período."
                )
            )
            return

        total = sum(repasse.valor_centavos for repasse in pendentes)
        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING(f"QUITAÇÃO — {instituicao.nome}"))
        for repasse in pendentes:
            self.stdout.write(
                f"  {repasse.created_at:%d/%m/%Y}  "
                f"{centavos_to_reais_str(repasse.valor_centavos):>10}  "
                f"pedido {repasse.pedido_id}"
            )
        self.stdout.write(
            f"\n{len(pendentes)} repasse(s), total {centavos_to_reais_str(total)}"
        )

        if not options["confirmar"]:
            self.stdout.write("")
            self.stdout.write(
                self.style.WARNING(
                    "SIMULAÇÃO — nada foi gravado. Repita com --confirmar "
                    "(e --comprovante) para quitar."
                )
            )
            return

        if not options["comprovante"]:
            raise CommandError(
                "--comprovante é obrigatório com --confirmar: sem a referência da "
                "transferência a quitação não é auditável."
            )

        with transaction.atomic():
            for repasse in pendentes:
                repasse.marcar_como_transferido(options["comprovante"])

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                f"{len(pendentes)} repasse(s) quitado(s), "
                f"{centavos_to_reais_str(total)}, comprovante "
                f"{options['comprovante']!r}."
            )
        )
