"""
Celery tasks para envio de notificações.
"""

import logging

import sentry_sdk
from celery import shared_task
from celery.exceptions import MaxRetriesExceededError
from django.conf import settings
from django.core.cache import cache
from django.core.mail import EmailMessage
from django.utils import timezone

from clama.freemium.models import FreemiumConfirmationToken
from clama.freemium.temp_password import desencriptar_senha_do_cache
from clama.notifications.services.email_sender import (
    enviar_email_confirmacao_freemium,
    enviar_email_oracao,
    enviar_oracao_email_freemium,
)
from clama.notifications.services.zapi_sender import ZapiSender
from clama.notifications.utils import format_telefone_e164
from clama.orders.models import CanalEntrega, Pedido, PedidoStatus

# Cache prefix usado pela view freemium para guardar a senha temporária
# até a task ler e remover. Mantido alinhado com `clama.freemium.api.views`.
FREEMIUM_TEMP_PASSWORD_CACHE_PREFIX = "freemium:temp_password:"

logger = logging.getLogger("clama.notifications.tasks")


# Template de mensagem WhatsApp pastoral
WHATSAPP_MESSAGE_TEMPLATE = """🙏 *{nome}*, sua oração está aqui.

{oracao}

---
_Enviado com carinho pelo Clama_
_clama.me_"""


@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def enviar_oracao_task(self, pedido_id: str) -> None:
    """
    Envia a oração gerada por email ou WhatsApp.

    Roteamento automático baseado em pedido.canal_entrega.

    Args:
        pedido_id: UUID do pedido (string)
    """
    pedido = Pedido.objects.get(id=pedido_id)

    # Idempotência: já enviado
    if pedido.status == PedidoStatus.ENVIADA:
        logger.info(
            "enviar_oracao_ja_enviada",
            extra={
                "event": "enviar_oracao_skipped",
                "pedido_id": pedido_id,
            },
        )
        return

    # Validação: oração deve existir
    if not pedido.oracao_gerada:
        logger.error(
            "enviar_oracao_sem_oracao",
            extra={
                "event": "enviar_oracao_no_prayer",
                "pedido_id": pedido_id,
            },
        )
        pedido.status = PedidoStatus.ERRO
        pedido.save(update_fields=["status", "updated_at"])
        return

    try:
        # Roteamento por canal
        if pedido.canal_entrega == CanalEntrega.EMAIL:
            _enviar_por_email(pedido)
        elif pedido.canal_entrega == CanalEntrega.WHATSAPP:
            _enviar_por_whatsapp(pedido)
        else:
            logger.warning(
                "enviar_oracao_canal_desconhecido",
                extra={
                    "event": "enviar_oracao_unknown_channel",
                    "pedido_id": pedido_id,
                    "canal": pedido.canal_entrega,
                },
            )
            # Fallback para email
            _enviar_por_email(pedido)

        pedido.status = PedidoStatus.ENVIADA
        pedido.save(update_fields=["status", "updated_at"])

        logger.info(
            "enviar_oracao_concluido",
            extra={
                "event": "enviar_oracao_completed",
                "pedido_id": pedido_id,
                "canal": pedido.canal_entrega,
            },
        )

    except Exception as exc:
        logger.warning(
            "enviar_oracao_erro",
            extra={
                "event": "enviar_oracao_error",
                "pedido_id": pedido_id,
                "canal": pedido.canal_entrega,
                "attempt": self.request.retries + 1,
                "error": str(exc),
            },
        )
        try:
            # Backoff exponencial: 30s, 60s, 120s
            countdown = 30 * (2 ** self.request.retries)
            raise self.retry(exc=exc, countdown=countdown)
        except MaxRetriesExceededError:
            pedido.status = PedidoStatus.ERRO
            pedido.save(update_fields=["status", "updated_at"])
            logger.error(
                "enviar_oracao_erro_persistente",
                extra={
                    "event": "enviar_oracao_failed",
                    "pedido_id": pedido_id,
                    "canal": pedido.canal_entrega,
                },
            )
            sentry_sdk.capture_exception(exc)


def _enviar_por_email(pedido: Pedido) -> None:
    """
    Envia oração por email.

    Se `pedido.eh_gratuito=True`, usa template freemium (com credenciais).
    Senão, fluxo padrão. A senha temporária é lida do cache (chave
    `freemium:temp_password:{user_id}`) e apagada após o envio. Se já
    expirou, envia o e-mail freemium sem o bloco de credenciais e loga
    um warning para Sentry.
    """
    if pedido.eh_gratuito:
        _enviar_email_freemium(pedido)
        return

    enviar_email_oracao(pedido)
    logger.info(
        "enviar_oracao_email_enviado",
        extra={
            "event": "email_sent",
            "pedido_id": str(pedido.id),
        },
    )


def _enviar_email_freemium(pedido: Pedido) -> None:
    """
    Envia oração com credenciais para pedido freemium.

    Lê a senha temporária encriptada do cache e a decripta com a chave
    `FREEMIUM_TEMP_PWD_KEY`. Em caso de falha de decrypt (chave rotacionada
    ou payload corrompido), o helper retorna `""` e logamos em Sentry — o
    e-mail é enviado sem o bloco de credenciais (mesmo fallback do "cache
    expirou").

    P-8: o cache.delete só acontece DEPOIS do `enviar_oracao_email_freemium`
    retornar com sucesso. Assim, se o SMTP falhar e a task re-tentar, a
    próxima execução ainda lê a senha. O TTL aumentado (24h em
    `views::TEMP_PASSWORD_TTL_SECONDS`) cobre delays de retry.

    P-V5 wave 2: idempotência via `Pedido.oracao_email_sent_at`. Se já
    setado (re-execução por Celery retry / double dispatch), retorna early
    sem reenviar — fecha race entre `cache.delete(senha_temp)` e
    `pedido.status` save que mandava email duplicado SEM credenciais.
    Após delivery confirmada, marca o campo PRIMEIRO, depois `cache.delete`
    — ordem importa pra evitar que retry pré-marca seja "limpo" e
    re-execute com cache vazio.
    """
    # Idempotência P-V5: se já enviado, no-op.
    if pedido.oracao_email_sent_at is not None:
        logger.info(
            "enviar_oracao_email_freemium_idempotente",
            extra={
                "event": "freemium_email_oracao_already_sent",
                "pedido_id": str(pedido.id),
                "sent_at": pedido.oracao_email_sent_at.isoformat(),
            },
        )
        return

    login_email = ""
    senha_temp = ""
    cache_key: str | None = None

    if pedido.user_id:
        cache_key = f"{FREEMIUM_TEMP_PASSWORD_CACHE_PREFIX}{pedido.user_id}"
        senha_cifrada = cache.get(cache_key) or ""
        senha_temp = desencriptar_senha_do_cache(senha_cifrada)
        if pedido.user is not None:
            login_email = pedido.user.email or pedido.email
        else:
            login_email = pedido.email

        if not senha_temp:
            logger.warning(
                "Senha temporária do freemium não encontrada no cache",
                extra={
                    "event": "freemium_senha_temp_expirada",
                    "pedido_id": str(pedido.id),
                    "user_id": str(pedido.user_id),
                },
            )
            sentry_sdk.capture_message(
                f"Freemium senha temp expirou para pedido {pedido.id}",
                level="warning",
            )
    else:
        login_email = pedido.email

    enviar_oracao_email_freemium(pedido, login_email, senha_temp)

    # P-V5: marca como enviado ANTES de limpar cache. Se o save falhar, a
    # próxima retry ainda encontra o cache populado e não duplica o email
    # sem credenciais (cache.delete só roda após este save bem-sucedido).
    pedido.oracao_email_sent_at = timezone.now()
    pedido.save(update_fields=["oracao_email_sent_at", "updated_at"])

    # Delivery confirmada (sem exceção) — agora apaga do cache.
    if cache_key and senha_temp:
        cache.delete(cache_key)

    logger.info(
        "enviar_oracao_email_freemium_enviado",
        extra={
            "event": "email_freemium_sent",
            "pedido_id": str(pedido.id),
            "credenciais_incluidas": bool(senha_temp),
        },
    )


def _enviar_por_whatsapp(pedido: Pedido) -> None:
    """Envia oração por WhatsApp."""
    if not pedido.telefone:
        raise ValueError("Pedido sem telefone para envio por WhatsApp")

    # Formata telefone para E.164
    telefone_e164 = format_telefone_e164(pedido.telefone)

    # Monta mensagem
    mensagem = WHATSAPP_MESSAGE_TEMPLATE.format(
        nome=pedido.nome,
        oracao=pedido.oracao_gerada,
    )

    # Envia via Z-API
    sender = ZapiSender()
    result = sender.send(telefone_e164, mensagem)

    # Persiste message_id para tracking
    pedido.whatsapp_message_id = result.get("provider_message_id", "")
    pedido.save(update_fields=["whatsapp_message_id", "updated_at"])

    logger.info(
        "enviar_oracao_whatsapp_enviado",
        extra={
            "event": "whatsapp_sent",
            "pedido_id": str(pedido.id),
            "message_id": result.get("provider_message_id", ""),
        },
    )


@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def enviar_email_confirmacao_freemium_task(
    self, pedido_id: str, token: str
) -> None:
    """
    Envia o e-mail com o link de confirmação (double opt-in) do fluxo
    freemium.

    Idempotente: se o Pedido não está mais em
    `AGUARDANDO_CONFIRMACAO_EMAIL` (ex.: token já consumido / saga rodou),
    log + return sem reenviar.

    Retry padrão da casa: 3 tentativas com backoff exponencial 30s, 60s, 120s.

    Args:
        pedido_id: UUID do pedido (string).
        token: token opaco da `FreemiumConfirmationToken` que vai no link.
    """
    try:
        pedido = Pedido.objects.get(id=pedido_id)
    except Pedido.DoesNotExist:
        logger.warning(
            "enviar_email_confirmacao_freemium_pedido_nao_encontrado",
            extra={
                "event": "freemium_confirmacao_pedido_not_found",
                "pedido_id": pedido_id,
            },
        )
        return

    if pedido.status != PedidoStatus.AGUARDANDO_CONFIRMACAO_EMAIL:
        logger.info(
            "enviar_email_confirmacao_freemium_status_mudou",
            extra={
                "event": "freemium_confirmacao_status_skipped",
                "pedido_id": pedido_id,
                "current_status": pedido.status,
            },
        )
        return

    # P-V8 wave 2: verifica se o token ainda é válido ANTES de mandar o
    # email. Cenário: a task ficou na fila por > 24h (worker travado /
    # backlog) — o token expirou. Mandar o email com link expirado gera
    # frustração + suporte. Marca pedido como ERRO e dispara Sentry alert.
    token_obj = FreemiumConfirmationToken.objects.filter(token=token).first()
    if (
        not token_obj
        or token_obj.expires_at <= timezone.now()
        or token_obj.used_at is not None
    ):
        logger.warning(
            "Token expirado ou consumido antes do email de confirmacao ser enviado",
            extra={
                "event": "freemium_confirmacao_token_invalido_pre_envio",
                "pedido_id": pedido_id,
                "token_existe": token_obj is not None,
                "token_expirado": (
                    token_obj is not None
                    and token_obj.expires_at <= timezone.now()
                ),
                "token_usado": (
                    token_obj is not None and token_obj.used_at is not None
                ),
            },
        )
        pedido.status = PedidoStatus.ERRO
        pedido.last_error = "token_expirado_antes_de_envio"
        pedido.save(update_fields=["status", "last_error", "updated_at"])
        sentry_sdk.capture_message(
            f"Freemium: token expirou antes do email de confirmação para pedido {pedido_id}",
            level="warning",
        )
        return

    # P-V2 wave 2: link de confirmação aponta para o FRONTEND, não o backend.
    # Frontend mostra página intermediária com botão "Confirmar minha
    # oração" que dispara o POST. Antes apontava direto pro backend GET, que
    # consumia o token quando mail scanners (Safe Links, Mimecast,
    # Proofpoint) faziam pre-fetch — saga rodava sem o usuário clicar.
    frontend_base = (
        getattr(settings, "FRONTEND_BASE_URL", "")
        or getattr(settings, "FRONTEND_URL", "")
        or "http://localhost:5173"
    ).rstrip("/")
    link_confirmacao = (
        f"{frontend_base}/oracao-gratis/confirmar?token={token}"
    )

    try:
        enviar_email_confirmacao_freemium(pedido, link_confirmacao)
    except Exception as exc:
        logger.warning(
            "enviar_email_confirmacao_freemium_erro",
            extra={
                "event": "freemium_confirmacao_email_error",
                "pedido_id": pedido_id,
                "attempt": self.request.retries + 1,
                "error": str(exc),
            },
        )
        try:
            countdown = 30 * (2 ** self.request.retries)
            raise self.retry(exc=exc, countdown=countdown)
        except MaxRetriesExceededError:
            logger.error(
                "enviar_email_confirmacao_freemium_falha_persistente",
                extra={
                    "event": "freemium_confirmacao_email_failed",
                    "pedido_id": pedido_id,
                },
            )
            sentry_sdk.capture_exception(exc)


@shared_task
def enviar_alerta_admin_task(pedido_id: str) -> None:
    """
    Envia alerta para admin quando pedido entra em ERRO.

    Envia email para ADMIN_ALERT_EMAIL e registra no Sentry.

    Args:
        pedido_id: UUID do pedido (string)
    """
    try:
        pedido = Pedido.objects.get(id=pedido_id)
    except Pedido.DoesNotExist:
        logger.warning(
            "alerta_admin_pedido_nao_encontrado",
            extra={
                "event": "admin_alert_pedido_not_found",
                "pedido_id": pedido_id,
            },
        )
        return

    # Verifica se ainda está em ERRO
    if pedido.status != PedidoStatus.ERRO:
        logger.info(
            "alerta_admin_status_mudou",
            extra={
                "event": "admin_alert_status_changed",
                "pedido_id": pedido_id,
                "current_status": pedido.status,
            },
        )
        return

    admin_email = getattr(settings, "ADMIN_ALERT_EMAIL", "contato@clama.me")

    # Monta email
    subject = f"[Clama] Pedido em ERRO - {str(pedido.id)[:8]}"
    message = f"""Um pedido entrou em status ERRO e requer atenção.

ID do Pedido: {pedido.id}
Nome: {pedido.nome}
Email: {pedido.email}
Telefone: {pedido.telefone or 'Não informado'}
Plano: {pedido.plano.nome}
Valor: {pedido.valor_reais_str}
Canal de Entrega: {pedido.canal_entrega}
Número de Retentativas: {pedido.retry_count}

Último Erro:
{pedido.last_error or 'Não registrado'}

---
Acesse o admin para mais detalhes: {settings.FRONTEND_URL}/admin/pedidos/{pedido.id}
"""

    try:
        EmailMessage(
            subject=subject,
            body=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[admin_email],
            reply_to=["contato@clama.me"],
        ).send(fail_silently=False)

        logger.info(
            "alerta_admin_enviado",
            extra={
                "event": "admin_alert_sent",
                "pedido_id": pedido_id,
                "admin_email": admin_email,
            },
        )
    except Exception as exc:
        logger.error(
            "alerta_admin_erro_email",
            extra={
                "event": "admin_alert_email_failed",
                "pedido_id": pedido_id,
                "error": str(exc),
            },
        )
        sentry_sdk.capture_exception(exc)

    # Registra no Sentry também
    sentry_sdk.capture_message(
        f"Pedido em ERRO: {pedido.id}",
        level="error",
    )
