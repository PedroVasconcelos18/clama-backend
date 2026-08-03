"""Exporta os posts do CMS próprio para o WordPress (Stories 4.1 e 4.3).

Idempotente por desenho: roda quantas vezes for preciso contra staging até o
mapeamento estabilizar. A identidade é `Post.id`, gravada no espelho — não o
slug, não a ordem, não a posição no arquivo.

⚠️ **Exporta por leitura, nunca por escrita.** `Post.save()` re-sanitiza
`conteudo_html` em toda gravação (`models.py:save`); um script que salvasse o
`Post` alteraria o conteúdo que está tentando preservar.
"""

from __future__ import annotations

import logging

from django.core.management.base import BaseCommand
from django.db import transaction

from clama.blog.models import Post, PostEspelho, PostEspelhoStatus, PostStatus
from clama.blog.services.wordpress_client import (
    WordPressClient,
    WordPressIndisponivel,
)

logger = logging.getLogger("clama.blog.exportacao")

# `rascunho` → `draft`, `publicado` → `publish`. O WordPress tem sete status;
# o CMS próprio tem dois, e só estes dois são origem possível.
MAPA_DE_STATUS = {
    PostStatus.RASCUNHO: "draft",
    PostStatus.PUBLICADO: "publish",
}

ESPELHO_POR_STATUS_WP = {
    "draft": PostEspelhoStatus.RASCUNHO,
    "publish": PostEspelhoStatus.PUBLICADO,
}


class Command(BaseCommand):
    help = "Exporta posts do Django para o WordPress, de forma idempotente."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Mostra o que faria, sem tocar no WordPress nem no banco.",
        )
        parser.add_argument(
            "--slug",
            action="append",
            default=[],
            help="Exporta só estes slugs. Repetível. Útil para reprocessar o "
            "que falhou sem varrer tudo de novo.",
        )
        parser.add_argument(
            "--somente-publicados",
            action="store_true",
            help="Ignora rascunhos. Rascunho não migrado é ausência decidida, "
            "e aparece no relatório de cobertura como tal.",
        )

    def handle(self, *args, **opcoes):
        dry_run = opcoes["dry_run"]
        cliente = WordPressClient()

        if not dry_run and not cliente.configurado:
            self.stderr.write(
                self.style.ERROR(
                    "WORDPRESS_API_URL/USER/APP_PASSWORD não configurados."
                )
            )
            return

        posts = Post.objects.all().order_by("created_at")

        if opcoes["slug"]:
            posts = posts.filter(slug__in=opcoes["slug"])
        if opcoes["somente_publicados"]:
            posts = posts.filter(status=PostStatus.PUBLICADO)

        criados = atualizados = 0
        # AC7: o que falhou é reportado **nominalmente**. "3 falharam" manda
        # alguém procurar do zero.
        falhas: list[tuple[str, str]] = []
        ignorados: list[tuple[str, str]] = []

        for post in posts:
            if opcoes["somente_publicados"] is False and post.status == (
                PostStatus.RASCUNHO
            ):
                # Rascunho migra como `draft` — só não migra se pedirem.
                pass

            try:
                acao = self._exportar(cliente, post, dry_run=dry_run)
            except WordPressIndisponivel as exc:
                # AC6: falha no meio não é destrutiva. O post que falhou fica
                # sem espelho, o anterior continua com o dele, e a
                # re-execução converge — nada foi apagado nem meio-escrito.
                falhas.append((post.slug, str(exc)))
                self.stderr.write(self.style.WARNING(f"  ✗ {post.slug}: {exc}"))
                continue

            if acao == "criado":
                criados += 1
                self.stdout.write(f"  + {post.slug}")
            elif acao == "atualizado":
                atualizados += 1
                self.stdout.write(f"  ~ {post.slug}")

        # AC2/AC3 da Story 4.3: cobertura, com nome e motivo para cada ausência.
        for post in Post.objects.filter(espelho__isnull=True):
            motivo = (
                "falhou nesta execução"
                if post.slug in {s for s, _ in falhas}
                else "fora do filtro desta execução"
            )
            ignorados.append((post.slug, motivo))

        self._relatorio(criados, atualizados, falhas, ignorados, dry_run=dry_run)

    def _exportar(self, cliente, post: Post, *, dry_run: bool) -> str:
        """Cria ou atualiza um post no WordPress e grava o mapeamento."""
        espelho = PostEspelho.objects.filter(post_legado=post).first()
        wp_post_id = espelho.wp_post_id if espelho else None

        campos = {
            # AC3: slug idêntico. É o que mantém as URLs indexadas vivas.
            "slug": post.slug,
            "title": post.titulo,
            "content": post.conteudo_html,
            "excerpt": post.excerpt,
            "status": MAPA_DE_STATUS[post.status],
        }

        # AC4: data de publicação preservada, para arquivo e feed ficarem
        # cronologicamente corretos. `date_gmt` porque `date` seria
        # interpretado no fuso do WordPress.
        if post.data_publicacao:
            campos["date_gmt"] = post.data_publicacao.isoformat()

        if post.historia_ilustrativa:
            # Post meta da Story 2.7 — o aviso do CDC art. 37 precisa
            # atravessar junto, senão a migração apaga uma exigência legal.
            campos["meta"] = {"clama_historia_ilustrativa": True}

        if dry_run:
            return "criado" if wp_post_id is None else "atualizado"

        corpo = cliente.criar_ou_atualizar_post(wp_post_id=wp_post_id, campos=campos)

        novo_id = int(corpo["id"])
        status_wp = str(corpo.get("status") or campos["status"])

        with transaction.atomic():
            # AC4 da Story 4.3: `update_or_create` sobre `wp_post_id`, para o
            # mapeamento **convergir** em vez de acumular. Reexecutar o
            # comando não cria segunda linha.
            PostEspelho.objects.update_or_create(
                wp_post_id=novo_id,
                defaults={
                    "post_legado": post,
                    "slug": str(corpo.get("slug") or post.slug)[:200],
                    "titulo": post.titulo[:200],
                    "status": ESPELHO_POR_STATUS_WP.get(
                        status_wp, PostEspelhoStatus.RASCUNHO
                    ),
                    "published_at": post.data_publicacao,
                    "url": str(corpo.get("link") or "")[:500],
                },
            )

        logger.info(
            "post_exportado",
            extra={
                "event": "post_exportado",
                "slug": post.slug,
                "wp_post_id": novo_id,
                "criado": wp_post_id is None,
            },
        )

        return "criado" if wp_post_id is None else "atualizado"

    def _relatorio(self, criados, atualizados, falhas, ignorados, *, dry_run):
        prefixo = "[dry-run] " if dry_run else ""

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                f"{prefixo}{criados} criados, {atualizados} atualizados, "
                f"{len(falhas)} falharam."
            )
        )

        if falhas:
            self.stdout.write("")
            self.stdout.write(self.style.ERROR("Falharam (rode de novo com --slug):"))
            for slug, motivo in falhas:
                self.stdout.write(f"  {slug}: {motivo}")

        # Cobertura: a ausência tem que ser **decidida**, não descoberta na
        # hora do backfill da Story 4.4 — que falha explicitamente ao
        # encontrar comentário sem post correspondente.
        if ignorados:
            self.stdout.write("")
            self.stdout.write(
                self.style.WARNING(
                    f"{len(ignorados)} posts sem correspondência no WordPress:"
                )
            )
            for slug, motivo in ignorados:
                self.stdout.write(f"  {slug}: {motivo}")
        else:
            self.stdout.write(
                self.style.SUCCESS("Cobertura: 100% dos posts têm espelho.")
            )
