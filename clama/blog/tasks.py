"""Celery tasks do app blog.

Stubs introduzidos na Story 2.5 — implementacao completa
(Vercel Deploy Hook + IndexNow + retry/backoff + alerta Sentry)
vem na Story 2.12.
"""

import logging

from celery import shared_task

logger = logging.getLogger("clama.blog.tasks")


@shared_task
def regenerar_blog_ssg(post_id: str) -> None:
    """Aciona rebuild Vercel do frontend SSG.

    TODO Story 2.12: chamar settings.VERCEL_DEPLOY_HOOK_URL com requests.post,
    timeout=30, max_retries=3, @retry_with_backoff. Em 3 falhas, alerta admin
    via Sentry + email.
    """
    logger.info("regenerar_blog_ssg_called", extra={"post_id": post_id})


@shared_task
def notificar_indexnow(post_id: str) -> None:
    """Notifica search engines via IndexNow API (best-effort).

    TODO Story 2.12: enviar POST pra IndexNow com lista de URLs canonicas
    do post. Idempotente — IndexNow aceita re-notificacao sem problema.
    """
    logger.info("notificar_indexnow_called", extra={"post_id": post_id})
