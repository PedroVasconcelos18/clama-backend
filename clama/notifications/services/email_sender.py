"""
Serviço de envio de email com oração.
"""

import logging
from urllib.parse import quote

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

from clama.orders.models import Pedido

logger = logging.getLogger("clama.notifications.email")

CLAMA_URL = "https://clama.me"


def _build_whatsapp_share_url(oracao_texto: str) -> str:
    """Monta a URL `wa.me` pré-preenchida — espelha o componente WhatsAppShareButton do front."""
    mensagem = (
        f'Recebi essa oração através do Clama:\n\n'
        f'"{oracao_texto}"\n\n'
        f'Faça também seu pedido: {CLAMA_URL}'
    )
    return f"https://wa.me/?text={quote(mensagem)}"


def enviar_email_oracao(pedido: Pedido) -> None:
    """
    Envia email com a oração para a Juliana.

    Args:
        pedido: Pedido com oração gerada
    """
    # Extrai primeiro nome para personalização
    primeiro_nome = pedido.nome.split()[0] if pedido.nome else "Amada"

    context = {
        "pedido": pedido,
        "primeiro_nome": primeiro_nome,
        "oracao": pedido.oracao_gerada,
        "whatsapp_share_url": _build_whatsapp_share_url(pedido.oracao_gerada),
    }

    # Renderiza templates
    body_html = render_to_string("email/oracao.html", context)
    body_text = render_to_string("email/oracao.txt", context)

    # Constrói email
    subject = f"Sua oração, {primeiro_nome} 🙏"
    email = EmailMultiAlternatives(
        subject=subject,
        body=body_text,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[pedido.email],
        reply_to=["contato@clama.me"],
    )
    email.attach_alternative(body_html, "text/html")

    # Envia
    email.send()

    logger.info(
        "Email enviado",
        extra={
            "event": "email_sent",
            "pedido_id": str(pedido.id),
        },
    )
