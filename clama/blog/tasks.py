"""Celery tasks do app blog.

`regenerar_blog_ssg` chama o Vercel Deploy Hook (rebuild SSG do frontend).
Retentavel em 5xx/Connection/Timeout; em MaxRetries dispara alerta admin
via Sentry.

`notificar_indexnow` notifica search engines (IndexNow) com a URL canônica
do post recém-publicado. Best-effort: falhas permanentes apenas logam
warning (sem Sentry — IndexNow é tolerante a falhas, alertas seriam ruído).
"""

import logging
from urllib.parse import urljoin

import requests
import sentry_sdk
from celery import shared_task
from celery.exceptions import MaxRetriesExceededError
from django.conf import settings

logger = logging.getLogger("clama.blog.tasks")

INDEXNOW_ENDPOINT = "https://api.indexnow.org/indexnow"
VERCEL_TIMEOUT_SECONDS = 30
INDEXNOW_TIMEOUT_SECONDS = 10


@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def regenerar_blog_ssg(self, post_id: str) -> None:
    """Aciona rebuild Vercel do frontend SSG.

    Idempotente: a fila de builds do Vercel absorve múltiplos hooks
    (o último vence). Retry em 5xx/Connection/Timeout com backoff
    exponencial 30s → 60s → 120s. Em 4xx ou após max_retries, alerta
    via Sentry mas não levanta — o site continua servindo a versão
    anterior do CDN.
    """
    url = settings.VERCEL_DEPLOY_HOOK_URL
    if not url:
        logger.warning(
            "vercel_deploy_hook_url_missing",
            extra={"event": "regenerar_blog_ssg_skip", "post_id": post_id},
        )
        return

    try:
        response = requests.post(url, timeout=VERCEL_TIMEOUT_SECONDS)
        response.raise_for_status()
        logger.info(
            "regenerar_blog_ssg_success",
            extra={
                "event": "regenerar_blog_ssg_success",
                "post_id": post_id,
                "status_code": response.status_code,
            },
        )
    except requests.HTTPError as exc:
        status_code = exc.response.status_code if exc.response is not None else 0
        if status_code >= 500:
            # Servidor errado — vale tentar de novo
            try:
                countdown = 30 * (2 ** self.request.retries)
                raise self.retry(exc=exc, countdown=countdown)
            except MaxRetriesExceededError:
                logger.error(
                    "regenerar_blog_ssg_failed_max_retries",
                    extra={
                        "event": "regenerar_blog_ssg_failed",
                        "post_id": post_id,
                        "status_code": status_code,
                    },
                )
                sentry_sdk.capture_exception(exc)
        else:
            # 4xx — config errada (URL inválida, token expirado).
            # Não retentar; alertar admin imediatamente.
            logger.error(
                "regenerar_blog_ssg_failed_client_error",
                extra={
                    "event": "regenerar_blog_ssg_4xx",
                    "post_id": post_id,
                    "status_code": status_code,
                },
            )
            sentry_sdk.capture_exception(exc)
    except (requests.ConnectionError, requests.Timeout) as exc:
        try:
            countdown = 30 * (2 ** self.request.retries)
            raise self.retry(exc=exc, countdown=countdown)
        except MaxRetriesExceededError:
            logger.error(
                "regenerar_blog_ssg_failed_network",
                extra={
                    "event": "regenerar_blog_ssg_failed",
                    "post_id": post_id,
                    "error": str(exc),
                },
            )
            sentry_sdk.capture_exception(exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def notificar_indexnow(self, post_id: str) -> None:
    """Notifica search engines via IndexNow API (best-effort).

    Não levanta exceção em falhas permanentes — apenas loga warning.
    Em falhas transientes (Connection/Timeout/5xx) retenta até 3x.
    """
    key = settings.INDEXNOW_KEY
    if not key:
        logger.warning(
            "indexnow_key_missing",
            extra={"event": "notificar_indexnow_skip", "post_id": post_id},
        )
        return

    # Lazy import pra evitar circular import com signals/models
    from .models import Post

    try:
        post = Post.objects.get(id=post_id)
    except Post.DoesNotExist:
        logger.info(
            "notificar_indexnow_post_not_found",
            extra={"event": "notificar_indexnow_skip", "post_id": post_id},
        )
        return

    base = settings.FRONTEND_PUBLIC_BLOG_BASE_URL.rstrip("/")
    canonical_url = urljoin(base + "/", f"blog/{post.slug}")
    host = base.split("://", 1)[-1].split("/", 1)[0]

    payload = {
        "host": host,
        "key": key,
        "urlList": [canonical_url],
    }

    try:
        response = requests.post(
            INDEXNOW_ENDPOINT,
            json=payload,
            timeout=INDEXNOW_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        logger.info(
            "notificar_indexnow_success",
            extra={
                "event": "notificar_indexnow_success",
                "post_id": post_id,
                "url": canonical_url,
                "status_code": response.status_code,
            },
        )
    except (requests.ConnectionError, requests.Timeout, requests.HTTPError) as exc:
        status_code = (
            exc.response.status_code
            if isinstance(exc, requests.HTTPError) and exc.response is not None
            else 0
        )
        # Só retenta em 5xx ou problemas de rede
        if status_code >= 500 or isinstance(
            exc, (requests.ConnectionError, requests.Timeout)
        ):
            try:
                raise self.retry(exc=exc)
            except MaxRetriesExceededError:
                # Best-effort: log warning, sem Sentry (ruído desnecessário)
                logger.warning(
                    "notificar_indexnow_failed_after_retries",
                    extra={
                        "event": "notificar_indexnow_failed",
                        "post_id": post_id,
                        "error": str(exc),
                    },
                )
        else:
            # 4xx — config errada, mas não levanta nem alerta admin
            logger.warning(
                "notificar_indexnow_client_error",
                extra={
                    "event": "notificar_indexnow_4xx",
                    "post_id": post_id,
                    "status_code": status_code,
                },
            )
