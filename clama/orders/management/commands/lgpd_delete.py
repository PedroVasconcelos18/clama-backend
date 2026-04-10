"""
Comando para deletar dados de um usuário conforme LGPD.

Usage:
    python manage.py lgpd_delete --email usuario@email.com           # Dry run
    python manage.py lgpd_delete --email usuario@email.com --confirm # Executa
"""

import logging

import sentry_sdk
from django.core.management.base import BaseCommand

from clama.orders.models import Pedido

logger = logging.getLogger("clama.lgpd")


class Command(BaseCommand):
    help = "Deleta todos os pedidos de um usuário (LGPD - direito de exclusão)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--email",
            type=str,
            required=True,
            help="E-mail do usuário para deletar dados",
        )
        parser.add_argument(
            "--confirm",
            action="store_true",
            help="Confirma a exclusão (sem este flag, apenas lista o que seria deletado)",
        )

    def handle(self, *args, **options):
        email = options["email"].lower().strip()
        confirm = options["confirm"]

        self.stdout.write(f"Buscando pedidos para: {email}")

        # Busca todos os pedidos do email
        pedidos = Pedido.objects.filter(email=email)
        count = pedidos.count()

        if count == 0:
            self.stdout.write(
                self.style.WARNING(f"Nenhum pedido encontrado para {email}")
            )
            return

        self.stdout.write(f"Encontrados {count} pedido(s):")

        # Lista pedidos que serão deletados
        for pedido in pedidos:
            self.stdout.write(
                f"  - {pedido.id} | {pedido.created_at.date()} | "
                f"{pedido.status} | {pedido.valor_reais_str}"
            )

        if not confirm:
            self.stdout.write("")
            self.stdout.write(
                self.style.WARNING(
                    "MODO DRY RUN: Nenhum dado foi deletado.\n"
                    "Execute com --confirm para deletar permanentemente."
                )
            )
            return

        # Confirma mais uma vez via input
        self.stdout.write("")
        self.stdout.write(
            self.style.WARNING(
                f"ATENÇÃO: Você está prestes a DELETAR PERMANENTEMENTE {count} pedido(s)."
            )
        )
        confirmation = input("Digite 'DELETAR' para confirmar: ")

        if confirmation != "DELETAR":
            self.stdout.write(self.style.ERROR("Operação cancelada."))
            return

        # Executa a exclusão
        deleted_ids = list(pedidos.values_list("id", flat=True))
        deleted_count, _ = pedidos.delete()

        # Log da ação para auditoria
        logger.info(
            "LGPD delete executed",
            extra={
                "event": "lgpd_delete",
                "email": email,
                "deleted_count": deleted_count,
                "deleted_ids": [str(id) for id in deleted_ids],
            },
        )

        # Também registra no Sentry para auditoria
        sentry_sdk.capture_message(
            f"LGPD delete: {deleted_count} pedidos deletados para {email}",
            level="info",
        )

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                f"Deletados {deleted_count} pedido(s) permanentemente."
            )
        )
        self.stdout.write(
            "A ação foi registrada no log e Sentry para fins de auditoria."
        )
