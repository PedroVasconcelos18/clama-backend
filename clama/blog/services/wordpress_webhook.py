"""Verificação de assinatura e tradução de status do webhook do WordPress.

Fonte **canônica** das duas coisas — o middleware e a view chamam daqui, para
não divergirem. Mesmo desenho de `payments/services/mercadopago_client.py`.
"""

import hashlib
import hmac
import logging

import sentry_sdk
from django.conf import settings

from clama.blog.models import PostEspelhoStatus

logger = logging.getLogger("clama.blog.webhook_auth")

HEADER_ASSINATURA = "X-Clama-Signature"

# Tradução dos status do WordPress (Story 3.3).
#
# O WordPress tem sete estados; o CMS próprio tinha dois. Colapsar tudo em
# rascunho/publicado perderia justamente a informação que decide se o widget
# de comentários aparece.
MAPA_DE_STATUS: dict[str, str] = {
    "publish": PostEspelhoStatus.PUBLICADO,
    "draft": PostEspelhoStatus.RASCUNHO,
    "future": PostEspelhoStatus.AGENDADO,
    "private": PostEspelhoStatus.PRIVADO,
    "pending": PostEspelhoStatus.PENDENTE,
    "trash": PostEspelhoStatus.LIXEIRA,
    # `auto-draft` e `inherit` (revisão) nunca deveriam chegar aqui, mas se
    # chegarem são rascunho — nunca público.
    "auto-draft": PostEspelhoStatus.RASCUNHO,
    "inherit": PostEspelhoStatus.RASCUNHO,
}


def traduzir_status(status_wp: str) -> str:
    """Traduz o status do WordPress para o do espelho.

    **Fail-closed**: status desconhecido vira `RASCUNHO`, nunca `PUBLICADO`.
    O contrário é o modo de falha silencioso que esta função existe para
    impedir — um status novo do WordPress faria o widget aceitar comentário em
    post que não está no ar.

    Desconhecido também alerta: se o WordPress introduzir um estado, queremos
    saber, não descobrir por um comentário órfão.
    """
    traduzido = MAPA_DE_STATUS.get(status_wp)

    if traduzido is None:
        logger.warning(
            "wordpress_status_desconhecido",
            extra={
                "event": "wordpress_status_desconhecido",
                "status_wp": status_wp,
                "fallback": PostEspelhoStatus.RASCUNHO.value,
            },
        )
        sentry_sdk.capture_message(
            f"Status desconhecido do WordPress: {status_wp!r}",
            level="warning",
        )
        return PostEspelhoStatus.RASCUNHO

    return traduzido


def status_efetivo(status_wp: str, *, protegido_por_senha: bool = False) -> str:
    """Status do espelho considerando também a proteção por senha.

    Proteção por senha é **atributo**, não status: no WordPress um post pode
    ser `publish` **e** exigir senha. Para o Clama isso é indistinguível de
    privado — quem não tem a senha não lê o post, e aceitar comentário ali
    produziria comentário em conteúdo que a pessoa não viu.
    """
    traduzido = traduzir_status(status_wp)

    if protegido_por_senha and traduzido == PostEspelhoStatus.PUBLICADO:
        return PostEspelhoStatus.PRIVADO

    return traduzido


def verificar_assinatura_webhook(request) -> bool:
    """Valida o HMAC-SHA256 do corpo cru contra o header de assinatura.

    Fonte canônica — usada pelo middleware. Retorna `False` (nunca levanta) em
    qualquer falha.

    ⚠️ Diferente do Mercado Pago, que assina um manifest de query params e
    headers, o WordPress assina **o corpo cru** (`WP-FR17`). Então esta função
    toca `request.body`, o que é seguro: o Django cacheia o `body` no primeiro
    acesso e o DRF relê dos bytes cacheados. O que não pode é consumir o
    stream via `request.read()`.
    """
    secret = getattr(settings, "WORDPRESS_WEBHOOK_SECRET", "")
    if not secret:
        logger.warning(
            "wordpress_webhook_auth: secret não configurado",
            extra={"event": "wordpress_webhook_auth", "ok": False},
        )
        return False

    assinatura = request.headers.get(HEADER_ASSINATURA, "")
    if not assinatura:
        logger.warning(
            "wordpress_webhook_auth: assinatura ausente",
            extra={"event": "wordpress_webhook_auth", "ok": False},
        )
        return False

    # `sha256=` é o prefixo que o `hash_hmac` do PHP produz nos exemplos
    # canônicos de webhook; aceitar com e sem evita um bug de integração que
    # só apareceria em produção.
    if assinatura.startswith("sha256="):
        assinatura = assinatura[len("sha256=") :]

    esperado = hmac.new(
        secret.encode(),
        request.body,
        hashlib.sha256,
    ).hexdigest()

    try:
        ok = hmac.compare_digest(esperado, assinatura)
    except TypeError:
        # A assinatura vem do header do atacante; caractere não-ASCII faz
        # `compare_digest` levantar.
        ok = False

    logger.info(
        "wordpress_webhook_auth",
        extra={"event": "wordpress_webhook_auth", "ok": ok},
    )
    return ok
