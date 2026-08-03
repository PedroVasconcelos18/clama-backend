"""
Invalida os refresh tokens emitidos antes da migração para cookie `HttpOnly`.

Story 1.8 / ADR-01. Trocar o mecanismo não invalida o que já foi emitido: um
refresh roubado antes do deploy continuaria valendo por 7 dias. A purga no
navegador (`purgeLegacyTokens`) remove o que está no `localStorage` de quem
voltar ao site — mas não alcança um token já exfiltrado.

Rodar UMA VEZ no deploy da Fase 0. Efeito: todas as sessões ativas caem e as
clientes precisam entrar de novo — é o custo consciente de encerrar a janela.
"""

from django.core.management.base import BaseCommand
from django.utils import timezone
from rest_framework_simplejwt.token_blacklist.models import (
    BlacklistedToken,
    OutstandingToken,
)


class Command(BaseCommand):
    help = "Blacklista todos os refresh tokens ainda válidos (migração ADR-01)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Mostra quantos seriam invalidados, sem gravar nada.",
        )

    def handle(self, *args, **options):
        agora = timezone.now()
        # `expires_at` no futuro = ainda utilizável. Os já expirados não
        # precisam de blacklist e só inflariam a tabela.
        candidatos = OutstandingToken.objects.filter(expires_at__gt=agora).exclude(
            id__in=BlacklistedToken.objects.values_list("token_id", flat=True)
        )
        total = candidatos.count()

        if options["dry_run"]:
            self.stdout.write(f"[dry-run] {total} refresh tokens seriam invalidados.")
            return

        if not total:
            self.stdout.write("Nenhum refresh token ativo a invalidar.")
            return

        BlacklistedToken.objects.bulk_create(
            [BlacklistedToken(token=token) for token in candidatos],
            ignore_conflicts=True,
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"{total} refresh tokens invalidados. Todas as sessões ativas caíram."
            )
        )
