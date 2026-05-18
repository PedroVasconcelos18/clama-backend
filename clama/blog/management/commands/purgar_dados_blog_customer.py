"""Management command — purga Comentarios + Reacoes de um customer (LGPD).

Atende solicitações de "direito ao esquecimento" no escopo do blog: deleta
todos os comentários e reações de um customer específico, MANTENDO:

- User account (precisa pra preservar pedidos do clama core / histórico)
- Pedido (clama core)
- CustomerBanido (auditoria de moderação — admin pode revogar manual depois)

Compliance: NFR11 (≤30 dias). Audit log: `purgar_dados_blog_customer_done`
com user_id + counts.

Uso:
    python manage.py purgar_dados_blog_customer <email> --dry-run
    python manage.py purgar_dados_blog_customer <email> --yes
"""

import logging

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from clama.blog.models import Comentario, Reacao

logger = logging.getLogger("clama.blog.management.purgar_lgpd")


class Command(BaseCommand):
    help = (
        "Purga Comentarios + Reacoes do blog de um customer (LGPD). "
        "User account, pedidos e banimentos NAO sao afetados."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "email",
            type=str,
            help="Email do customer (case-insensitive)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Conta o que seria deletado sem persistir mudancas",
        )
        parser.add_argument(
            "--yes",
            action="store_true",
            help="Confirma execucao sem prompt interativo",
        )

    def handle(self, *args, **options):
        email = options["email"]
        dry_run = options["dry_run"]
        confirmed = options["yes"]

        User = get_user_model()
        try:
            user = User.objects.get(email__iexact=email)
        except User.DoesNotExist:
            raise CommandError(f"Customer com email {email!r} nao encontrado.")

        if not dry_run and not confirmed:
            self.stdout.write(
                self.style.WARNING(
                    f"Voce esta prestes a apagar TODOS os comentarios e "
                    f"reacoes de {user.email} (user_id={user.id}). "
                    f"User account e pedidos NAO serao tocados."
                )
            )
            resp = input("Confirma? [y/N]: ").strip().lower()
            if resp != "y":
                self.stdout.write("Cancelado.")
                return

        with transaction.atomic():
            n_comentarios = Comentario.objects.filter(customer=user).count()
            n_reacoes = Reacao.objects.filter(customer=user).count()

            if dry_run:
                self.stdout.write(
                    self.style.NOTICE(
                        f"[DRY-RUN] Seriam removidos: {n_comentarios} "
                        f"comentarios, {n_reacoes} reacoes de {user.email} "
                        f"(user_id={user.id}). Nenhuma mudanca persistida."
                    )
                )
                logger.info(
                    "purgar_dados_blog_customer_dry_run",
                    extra={
                        "event": "purgar_dados_blog_customer_dry_run",
                        "user_id": user.id,
                        "n_comentarios": n_comentarios,
                        "n_reacoes": n_reacoes,
                    },
                )
                return

            Comentario.objects.filter(customer=user).delete()
            Reacao.objects.filter(customer=user).delete()

        self.stdout.write(
            self.style.SUCCESS(
                f"Removidos: {n_comentarios} comentarios, {n_reacoes} "
                f"reacoes de {user.email} (user_id={user.id})"
            )
        )
        logger.info(
            "purgar_dados_blog_customer_done",
            extra={
                "event": "purgar_dados_blog_customer_done",
                "user_id": user.id,
                "n_comentarios": n_comentarios,
                "n_reacoes": n_reacoes,
            },
        )
