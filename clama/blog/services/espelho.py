"""Resolução do `PostEspelho` no caminho de escrita (Story 3.10).

A ordem de eventos **não** garante que o espelho exista quando o primeiro
comentário chega. O post fica público no instante da publicação; o espelho
depende do webhook, que é assíncrono e pode falhar. A janela é pequena — e é
exatamente a janela em que o post é novo, quando o tráfego e a chance de
comentário são maiores.

Sem isto, o primeiro leitor a comentar recebe erro de FK.
"""

from __future__ import annotations

import logging
from datetime import UTC

from django.db import IntegrityError, transaction

from clama.blog.models import PostEspelho
from clama.blog.services.wordpress_client import (
    WordPressClient,
)
from clama.blog.services.wordpress_webhook import status_efetivo
from clama.core.exceptions import PastoralAPIException

logger = logging.getLogger("clama.blog.espelho")


class PostNaoEncontrado(PastoralAPIException):
    """O post não existe nem no espelho nem no WordPress."""

    status_code = 404
    code = "post_nao_encontrado"
    message = "Post não encontrado."
    pastoral_message = "Não encontramos este texto. Ele pode ter saído do ar."


class PostNaoAceitaInteracao(PastoralAPIException):
    """O post existe, mas não está publicado.

    409 e não 403: não é falta de permissão da Juliana, é estado do post. E o
    frontend precisa distinguir para preservar o que ela digitou.
    """

    status_code = 409
    code = "post_nao_aceita_interacao"
    message = "Post não está publicado."
    pastoral_message = (
        "Este texto saiu do ar enquanto você escrevia. "
        "Copiamos o que você digitou — guarde, e tente de novo quando ele voltar."
    )


def resolver_espelho(slug: str, *, exigir_publicado: bool = True) -> PostEspelho:
    """Devolve o espelho do post, criando-o sob demanda se preciso.

    A criação sob demanda produz **exatamente** a linha que o webhook
    produziria — mesmos campos, mesma tradução de status —, para que a chegada
    posterior do webhook seja um `update_or_create` sobre a mesma linha, e não
    uma duplicata.

    Raises:
        PostNaoAceitaInteracao: post existe mas não está publicado.
        PostNaoEncontrado: nem o espelho nem o WordPress conhecem o slug.
        WordPressIndisponivel: não deu para perguntar. **Não** é o mesmo que
            "não existe" — quem chama decide, mas nunca deve tratar como 404.
    """
    espelho = (
        PostEspelho.objects.filter(slug=slug)
        .order_by("-published_at", "-created_at")
        .first()
    )

    if espelho is None:
        espelho = _criar_a_partir_do_wordpress(slug)

    if exigir_publicado and not espelho.aceita_interacao:
        raise PostNaoAceitaInteracao()

    return espelho


def _criar_a_partir_do_wordpress(slug: str) -> PostEspelho:
    cliente = WordPressClient()

    if not cliente.configurado:
        # **Não configurado ≠ indisponível.** São duas implantações
        # diferentes:
        #
        #   sem credencial   não existe WordPress neste ambiente. Um slug sem
        #                    espelho simplesmente não existe → 404.
        #   com credencial   existe e não respondeu → 503, e quem chama
        #                    decide; nunca vira 404.
        #
        # Confundir as duas fazia um rascunho do CMS próprio devolver 500 em
        # vez de 404 durante toda a transição.
        logger.debug(
            "espelho_sem_wordpress_configurado",
            extra={"event": "espelho_resolucao", "slug": slug},
        )
        raise PostNaoEncontrado()

    post = cliente.buscar_post_por_slug(slug)

    if post is None:
        logger.info(
            "espelho_slug_inexistente_no_wordpress",
            extra={"event": "espelho_resolucao", "slug": slug},
        )
        raise PostNaoEncontrado()

    campos = {
        "slug": str(post.get("slug") or slug)[:200],
        "titulo": str(
            (post.get("title") or {}).get("raw")
            or (post.get("title") or {}).get("rendered")
            or ""
        )[:200],
        "status": status_efetivo(
            str(post.get("status") or ""),
            protegido_por_senha=bool(post.get("password")),
        ),
        "published_at": _data(post.get("date_gmt")),
        "url": str(post.get("link") or "")[:500],
    }

    wp_post_id = int(post["id"])

    try:
        with transaction.atomic():
            espelho, criado = PostEspelho.objects.get_or_create(
                wp_post_id=wp_post_id, defaults=campos
            )
    except IntegrityError:
        # Corrida com o webhook chegando no mesmo instante: o `atomic` aninhado
        # cria savepoint para o INSERT falho não envenenar a transação externa,
        # e a linha que venceu serve igual.
        espelho = PostEspelho.objects.get(wp_post_id=wp_post_id)
        criado = False

    logger.info(
        "espelho_resolvido_sob_demanda",
        extra={
            "event": "espelho_resolucao",
            "slug": slug,
            "wp_post_id": wp_post_id,
            "criado": criado,
        },
    )
    return espelho


def _data(valor):
    """`date_gmt` do WordPress vem sem timezone, mas é UTC."""

    from django.utils import timezone
    from django.utils.dateparse import parse_datetime

    if not valor:
        return None
    parsed = parse_datetime(str(valor))
    if parsed is None:
        return None
    if timezone.is_naive(parsed):
        return parsed.replace(tzinfo=UTC)
    return parsed
