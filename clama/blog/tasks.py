"""Celery tasks do app blog.

`regenerar_blog_ssg` chama o Vercel Deploy Hook (rebuild SSG do frontend).
Retentavel em 5xx/Connection/Timeout; em MaxRetries dispara alerta admin
via Sentry.

`notificar_indexnow` notifica search engines (IndexNow) com a URL canônica
do post recém-publicado. Best-effort: falhas permanentes apenas logam
warning (sem Sentry — IndexNow é tolerante a falhas, alertas seriam ruído).

`enviar_alerta_comentarios_diario` (beat) — resumo diário pro admin.

`purgar_ips_antigos` (beat) — limpa IPs > 180 dias (LGPD compliance).
"""

import logging
from datetime import UTC, datetime, timedelta
from urllib.parse import urljoin

import requests
import sentry_sdk
from celery import shared_task
from celery.exceptions import MaxRetriesExceededError
from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

logger = logging.getLogger("clama.blog.tasks")

INDEXNOW_ENDPOINT = "https://api.indexnow.org/indexnow"
VERCEL_TIMEOUT_SECONDS = 30
INDEXNOW_TIMEOUT_SECONDS = 10
COMENTARIOS_DIARIO_LOOKBACK = timedelta(hours=24)
IP_RETENTION_DAYS = 180


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
                countdown = 30 * (2**self.request.retries)
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
            countdown = 30 * (2**self.request.retries)
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


@shared_task
def enviar_alerta_comentarios_diario() -> dict:
    """Envia email diário pro admin com resumo dos comentários das últimas 24h.

    No-op se não há comentários novos (evita ruído no inbox do admin).
    Comentários `is_suspeito=True` aparecem primeiro no resumo.
    """
    from .models import Comentario

    cutoff = timezone.now() - COMENTARIOS_DIARIO_LOOKBACK
    novos = list(
        Comentario.objects.filter(created_at__gte=cutoff)
        .select_related("post", "customer")
        .order_by("-is_suspeito", "-created_at")
    )
    n_novos = len(novos)
    n_suspeitos = sum(1 for c in novos if c.is_suspeito)

    if n_novos == 0:
        logger.info(
            "alerta_comentarios_diario_skip",
            extra={"event": "alerta_comentarios_diario_skip"},
        )
        return {"n_novos": 0, "n_suspeitos": 0, "n_email_enviados": 0}

    admin_email = getattr(settings, "ADMIN_ALERT_EMAIL", "")
    if not admin_email:
        logger.warning(
            "admin_alert_email_missing",
            extra={"event": "alerta_comentarios_diario_no_recipient"},
        )
        return {
            "n_novos": n_novos,
            "n_suspeitos": n_suspeitos,
            "n_email_enviados": 0,
        }

    subject = (
        f"Resumo de comentários do blog ({n_novos} novos, {n_suspeitos} suspeitos)"
    )
    linhas = [
        f"Resumo das últimas {COMENTARIOS_DIARIO_LOOKBACK.total_seconds() / 3600:.0f}h",
        "",
    ]
    for c in novos:
        flag = " [SUSPEITO]" if c.is_suspeito else ""
        snippet = c.conteudo[:100] + ("…" if len(c.conteudo) > 100 else "")
        linhas.append(f"- /blog/{c.post.slug} | {c.customer.email}{flag}: {snippet}")
    linhas.append("")
    linhas.append("Modere em: /admin/blog/comentarios")
    body = "\n".join(linhas)

    send_mail(
        subject=subject,
        message=body,
        from_email=None,  # usa DEFAULT_FROM_EMAIL
        recipient_list=[admin_email],
        fail_silently=False,
    )
    logger.info(
        "alerta_comentarios_diario_sent",
        extra={
            "event": "alerta_comentarios_diario_sent",
            "n_novos": n_novos,
            "n_suspeitos": n_suspeitos,
        },
    )
    return {
        "n_novos": n_novos,
        "n_suspeitos": n_suspeitos,
        "n_email_enviados": 1,
    }


@shared_task
def purgar_ips_antigos() -> dict:
    """Zera `ip_address` de comentários com `created_at < now - 180 dias`.

    LGPD/Marco Civil: IP é necessário por 6 meses pra rastreabilidade,
    após isso vira lixo (não-essencial pra moderação). Zerar em vez de
    deletar comentário preserva o histórico da conversa.
    """
    from .models import Comentario

    cutoff = timezone.now() - timedelta(days=IP_RETENTION_DAYS)
    # NOTA: `ip_address` é EncryptedCharField — `.exclude(ip_address="")` no
    # ORM não funciona porque compara contra blob encriptado. Iteramos em
    # Python pra contar/purgar apenas os realmente preenchidos. Volume é
    # tipicamente pequeno (varredura diária; 6+ meses de dados raramente
    # chega na ordem de 10k+ por tenant).
    n_purgados = 0
    candidatos = Comentario.objects.filter(created_at__lt=cutoff).only(
        "id", "ip_address"
    )
    for c in candidatos:
        if c.ip_address:
            Comentario.objects.filter(id=c.id).update(ip_address="")
            n_purgados += 1
    logger.info(
        "purgar_ips_antigos_done",
        extra={"event": "purgar_ips_antigos", "n_purgados": n_purgados},
    )
    return {"n_purgados": n_purgados}


@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def sincronizar_post_espelho(self, webhook_evento_id: str) -> None:
    """Aplica um evento do WordPress ao `PostEspelho` (Stories 3.2 e 3.3).

    Idempotente: o efeito de aplicar o mesmo evento duas vezes é idêntico ao
    de aplicá-lo uma — `update_or_create` por `wp_post_id`, sem acumular nada.

    **Nunca apaga linha.** `post_removido` grava `LIXEIRA`. Apagar derrubaria
    o `PROTECT` das FKs de `Comentario` e `Reacao`, que é o que preserva
    comentários e IPs sob a retenção de 6 meses do Marco Civil.
    """
    from clama.blog.models import PostEspelho, PostEspelhoStatus
    from clama.blog.services.wordpress_webhook import status_efetivo
    from clama.payments.models import WebhookEvento, WebhookEventoStatus

    try:
        evento = WebhookEvento.objects.get(id=webhook_evento_id)
    except WebhookEvento.DoesNotExist:
        # Não retenta: se a linha não existe, ela não vai passar a existir.
        logger.warning(
            "sincronizar_post_espelho_evento_ausente",
            extra={
                "event": "sincronizar_post_espelho_skip",
                "webhook_evento_id": webhook_evento_id,
            },
        )
        return

    if evento.status in (
        WebhookEventoStatus.PROCESSADO,
        WebhookEventoStatus.IGNORADO,
    ):
        logger.info(
            "sincronizar_post_espelho_ja_terminal",
            extra={
                "event": "sincronizar_post_espelho_skip",
                "webhook_evento_id": webhook_evento_id,
                "status": evento.status,
            },
        )
        return

    payload = evento.payload or {}

    try:
        wp_post_id = int(payload.get("wp_post_id"))
    except (TypeError, ValueError):
        evento.status = WebhookEventoStatus.ERRO
        evento.save(update_fields=["status", "updated_at"])
        logger.warning(
            "sincronizar_post_espelho_wp_post_id_invalido",
            extra={
                "event": "sincronizar_post_espelho_erro",
                "webhook_evento_id": webhook_evento_id,
            },
        )
        return

    if evento.event_type == "post_removido":
        # Remoção no WordPress = lixeira aqui. Ver docstring.
        novo_status = PostEspelhoStatus.LIXEIRA
    else:
        novo_status = status_efetivo(
            str(payload.get("status") or ""),
            protegido_por_senha=_como_bool(payload.get("protegido_por_senha")),
        )

    published_at = parse_datetime(str(payload.get("published_at") or "")) or None
    if published_at is not None and timezone.is_naive(published_at):
        published_at = timezone.make_aware(published_at)

    with transaction.atomic():
        espelho, criado = PostEspelho.objects.update_or_create(
            wp_post_id=wp_post_id,
            defaults={
                "slug": str(payload.get("slug") or "")[:200],
                "titulo": str(payload.get("titulo") or "")[:200],
                "status": novo_status,
                "published_at": published_at,
                "url": str(payload.get("url") or "")[:500],
            },
        )
        evento.status = WebhookEventoStatus.PROCESSADO
        evento.save(update_fields=["status", "updated_at"])

    logger.info(
        "sincronizar_post_espelho_ok",
        extra={
            "event": "sincronizar_post_espelho_ok",
            "wp_post_id": wp_post_id,
            "criado": criado,
            "status": novo_status,
            "espelho_id": str(espelho.id),
        },
    )


def _como_bool(valor) -> bool:
    """Interpreta o booleano que chega form-encoded.

    Corpo form-encoded não tem tipo: o PHP manda `"1"`, `"true"` ou `""`, e
    `bool("0")` em Python é `True`. Sem esta tradução, um post desprotegido
    marcado com `"0"` viraria protegido.
    """
    if isinstance(valor, bool):
        return valor
    return str(valor).strip().lower() in {"1", "true", "yes", "on"}


# Reconciliação do espelho (Story 3.6).
#
# ⚠️ A cadência **é** o limite superior da janela de dessincronia. O WordPress
# não tem fila de retentativa para `wp_remote_post`: se a entrega do webhook
# falhar — origem fora do ar, timeout, deploy do Django em curso —, o evento se
# perde em silêncio. A idempotência trata duplicata; ela não trata ausência.
# Esta task é o mecanismo de correção primário, e a cada 15 minutos significa
# "o espelho pode ficar até 15 minutos errado".
RECONCILIACAO_POR_PAGINA = 100
RECONCILIACAO_MAX_PAGINAS = 50


@shared_task
def reconciliar_espelho_com_wordpress() -> dict:
    """Corrige divergências entre o espelho e o WordPress.

    **Nunca remove linha**, e nunca conclui exclusão por ausência: post que
    não aparece na resposta é ignorado, não apagado. Uma listagem incompleta
    por falha transitória viraria remoção em massa de vínculo de comentário —
    é a decisão nº 5 do ADR-02, e a mesma regra do AC7 da Story 3.4 vista de
    outro ângulo.

    Returns:
        Contadores para inspeção em Flower e log.
    """
    from clama.blog.models import PostEspelho
    from clama.blog.services.wordpress_client import (
        WordPressClient,
        WordPressIndisponivel,
    )
    from clama.blog.services.wordpress_webhook import status_efetivo

    contadores = {
        "paginas_lidas": 0,
        "posts_vistos": 0,
        "criados": 0,
        "atualizados": 0,
        "sem_mudanca": 0,
        "abortada": False,
        "motivo": "",
    }

    cliente = WordPressClient()

    if not cliente.configurado:
        contadores["abortada"] = True
        contadores["motivo"] = "credencial_ausente"
        logger.warning(
            "reconciliacao_abortada",
            extra={"event": "reconciliacao_abortada", "motivo": "credencial_ausente"},
        )
        return contadores

    vistos: list[dict] = []
    pagina = 1

    while pagina <= RECONCILIACAO_MAX_PAGINAS:
        try:
            posts, total_paginas = cliente.listar_posts(
                pagina=pagina, por_pagina=RECONCILIACAO_POR_PAGINA
            )
        except WordPressIndisponivel as exc:
            # Aborta inteira. Aplicar o que já foi lido deixaria o espelho num
            # estado que nem o WordPress nem a reconciliação anterior
            # descrevem — pior que não fazer nada.
            contadores["abortada"] = True
            contadores["motivo"] = "wordpress_indisponivel"
            logger.warning(
                "reconciliacao_abortada",
                extra={
                    "event": "reconciliacao_abortada",
                    "motivo": "wordpress_indisponivel",
                    "erro": str(exc),
                    "pagina": pagina,
                },
            )
            sentry_sdk.capture_message(
                "Reconciliação do espelho abortada: WordPress indisponível",
                level="warning",
            )
            return contadores

        vistos.extend(posts)
        contadores["paginas_lidas"] += 1

        if pagina >= total_paginas:
            break
        pagina += 1
    else:
        # Saiu pelo teto de páginas: a listagem está incompleta e não sabemos
        # o que ficou de fora. Abortar é o único desfecho seguro.
        contadores["abortada"] = True
        contadores["motivo"] = "listagem_incompleta"
        logger.warning(
            "reconciliacao_abortada",
            extra={
                "event": "reconciliacao_abortada",
                "motivo": "listagem_incompleta",
                "paginas_lidas": contadores["paginas_lidas"],
            },
        )
        sentry_sdk.capture_message(
            "Reconciliação do espelho abortada: listagem incompleta",
            level="warning",
        )
        return contadores

    contadores["posts_vistos"] = len(vistos)

    for post in vistos:
        try:
            wp_post_id = int(post["id"])
        except (KeyError, TypeError, ValueError):
            continue

        desejado = {
            "slug": str(post.get("slug") or "")[:200],
            "titulo": str(
                (post.get("title") or {}).get("raw")
                or (post.get("title") or {}).get("rendered")
                or ""
            )[:200],
            "status": status_efetivo(
                str(post.get("status") or ""),
                protegido_por_senha=bool(post.get("password")),
            ),
            "published_at": _data_do_wordpress(post.get("date_gmt")),
            "url": str(post.get("link") or "")[:500],
        }

        espelho = PostEspelho.objects.filter(wp_post_id=wp_post_id).first()

        if espelho is None:
            PostEspelho.objects.create(wp_post_id=wp_post_id, **desejado)
            contadores["criados"] += 1
            continue

        divergentes = [
            campo
            for campo, valor in desejado.items()
            if getattr(espelho, campo) != valor
        ]

        if not divergentes:
            # Early-return por linha: o caso comum é não haver divergência, e
            # gravar mesmo assim mexeria em `updated_at` de tudo a cada 15
            # minutos, poluindo qualquer auditoria por data.
            contadores["sem_mudanca"] += 1
            continue

        for campo, valor in desejado.items():
            setattr(espelho, campo, valor)
        espelho.save(update_fields=[*desejado.keys(), "updated_at"])
        contadores["atualizados"] += 1

    logger.info(
        "reconciliacao_concluida",
        extra={"event": "reconciliacao_concluida", **contadores},
    )
    return contadores


def _data_do_wordpress(valor) -> datetime | None:
    """`date_gmt` do WordPress vem sem timezone, mas é UTC.

    Interpretar como horário local produziria posts publicados "no futuro" ou
    "há três horas" dependendo do fuso do servidor.

    `dt_timezone.utc` e não `django.utils.timezone.utc`: este último está
    deprecado no Django 4.2 e foi removido no 5.0.
    """
    if not valor:
        return None
    parsed = parse_datetime(str(valor))
    if parsed is None:
        return None
    if timezone.is_naive(parsed):
        return parsed.replace(tzinfo=UTC)
    return parsed
