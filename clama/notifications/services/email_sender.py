"""
Serviço de envio de email com oração.

P-V14 wave 2: as funções de envio do fluxo freemium (`enviar_email_confirmacao_freemium`
e `enviar_oracao_email_freemium`) estão decoradas com `@with_retry` para
cumprir literalmente o frozen "Always" — `@with_retry` em Resend +
Turnstile. A camada de retry da task Celery (`max_retries=3,
default_retry_delay=30`) permanece como fallback final pra falhas que
escapem das 3 tentativas internas (ex.: container reciclado mid-retry).
"""

import logging
import smtplib
from urllib.parse import quote

import requests
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

from clama.core.retry import with_retry
from clama.orders.models import Pedido

logger = logging.getLogger("clama.notifications.email")

# Exceções da Resend / Anymail / SMTP que valem retry. Deixamos
# requests.RequestException pois Anymail (Resend backend) usa requests
# internamente e propaga a mesma família.
_EMAIL_RETRY_EXCEPTIONS = (
    smtplib.SMTPException,
    requests.RequestException,
    OSError,  # cobertura de socket-level errors no smtp lib
)

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


@with_retry(
    max_attempts=3,
    backoff_seconds=[1, 2, 4],
    retriable_exceptions=_EMAIL_RETRY_EXCEPTIONS,
)
def enviar_oracao_email_freemium(
    pedido: Pedido,
    login_email: str,
    senha_temporaria: str,
) -> None:
    """
    Envia o e-mail de oração no fluxo freemium, com bloco de credenciais.

    Diferenças do `enviar_email_oracao`:
    - Usa o template `email/oracao_freemium.html` (com bloco visual de
      credenciais).
    - Subject sem emoji ("Sua oração chegou, {nome}") por consistência com
      o tom mais sóbrio do fluxo gratuito.
    - Inclui `login_email` e `senha_temporaria` no contexto. Se vierem
      vazios (ex.: senha temp expirou no cache), o template oculta o
      bloco — ainda envia a oração.

    Args:
        pedido: Pedido com oração gerada (eh_gratuito=True esperado).
        login_email: e-mail usado como login do User criado.
        senha_temporaria: senha temporária. Pode ser vazia se já expirou.
    """
    primeiro_nome = pedido.nome.split()[0] if pedido.nome else "Amada"

    # URL absoluta do login customer — usada no bloco de credenciais
    # quando senha temp foi incluída. Frontend ressalva pasterol no flash
    # após login (force_change_password=True → /trocar-senha).
    frontend_base = (
        getattr(settings, "FRONTEND_BASE_URL", "")
        or getattr(settings, "FRONTEND_URL", "")
        or "http://localhost:5173"
    ).rstrip("/")
    login_url = f"{frontend_base}/login"

    context = {
        "pedido": pedido,
        "primeiro_nome": primeiro_nome,
        "oracao": pedido.oracao_gerada,
        "login_email": login_email or "",
        "senha_temporaria": senha_temporaria or "",
        "login_url": login_url,
    }

    body_html = render_to_string("email/oracao_freemium.html", context)
    body_text = render_to_string("email/oracao_freemium.txt", context)

    subject = f"Sua oração chegou, {primeiro_nome}"
    email = EmailMultiAlternatives(
        subject=subject,
        body=body_text,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[pedido.email],
        reply_to=["contato@clama.me"],
    )
    email.attach_alternative(body_html, "text/html")
    email.send()

    logger.info(
        "Email freemium enviado",
        extra={
            "event": "email_freemium_sent",
            "pedido_id": str(pedido.id),
            "credenciais_incluidas": bool(login_email and senha_temporaria),
        },
    )


@with_retry(
    max_attempts=3,
    backoff_seconds=[1, 2, 4],
    retriable_exceptions=_EMAIL_RETRY_EXCEPTIONS,
)
def enviar_email_confirmacao_freemium(
    pedido: Pedido,
    link_confirmacao: str,
) -> None:
    """
    Envia o e-mail de confirmação (double opt-in) do fluxo freemium.

    Chamado após a submissão em `PedidoFreemiumCreateView` — o usuário
    recebe um link único; ao clicar, a `FreemiumConfirmarView` valida o
    token e roda a saga (User + blacklist + dispatch da geração).

    Args:
        pedido: Pedido em status `AGUARDANDO_CONFIRMACAO_EMAIL`.
        link_confirmacao: URL absoluta com o token (`?token=...`) que o
            backend usa para validar e consumir.
    """
    primeiro_nome = pedido.nome.split()[0] if pedido.nome else "Amada"

    context = {
        "pedido": pedido,
        "primeiro_nome": primeiro_nome,
        "link_confirmacao": link_confirmacao,
        "expira_em_horas": 24,
    }

    body_html = render_to_string("email/confirmacao_freemium.html", context)
    body_text = render_to_string("email/confirmacao_freemium.txt", context)

    subject = "Confirme sua oração — clama"
    email = EmailMultiAlternatives(
        subject=subject,
        body=body_text,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[pedido.email],
        reply_to=["contato@clama.me"],
    )
    email.attach_alternative(body_html, "text/html")
    email.send()

    logger.info(
        "Email de confirmação freemium enviado",
        extra={
            "event": "email_confirmacao_freemium_sent",
            "pedido_id": str(pedido.id),
        },
    )


@with_retry(
    max_attempts=3,
    backoff_seconds=[1, 2, 4],
    retriable_exceptions=_EMAIL_RETRY_EXCEPTIONS,
)
def enviar_email_recuperacao_senha(
    email_destino: str,
    primeiro_nome: str,
    senha_temporaria: str,
) -> None:
    """
    Envia o e-mail de recuperação de senha (fluxo "Esqueci minha senha").

    Disparado **síncrono** pela `ForgotPasswordView` quando o e-mail existe
    e é de um customer ativo. A view já gerou a senha temporária, aplicou
    no `User` (`set_password`) e setou `force_change_password=True`; aqui só
    entregamos a credencial. O `@with_retry` espelha os outros envios do
    fluxo freemium (3 tentativas internas + backoff) — não há camada Celery
    aqui porque o envio é síncrono no request.

    NÃO depende de `Pedido` — recuperação de senha é independente de
    pedidos. O log não inclui a senha (apenas o domínio do e-mail para
    diagnóstico sem vazar PII).

    Args:
        email_destino: e-mail do customer (login).
        primeiro_nome: primeiro nome para personalização (fallback "Amada").
        senha_temporaria: senha temporária recém-gerada (texto plano,
            usada uma única vez no template; nunca logada).
    """
    nome = primeiro_nome or "Amada"

    frontend_base = (
        getattr(settings, "FRONTEND_BASE_URL", "")
        or getattr(settings, "FRONTEND_URL", "")
        or "http://localhost:5173"
    ).rstrip("/")
    login_url = f"{frontend_base}/login"

    context = {
        "primeiro_nome": nome,
        "login_email": email_destino,
        "senha_temporaria": senha_temporaria,
        "login_url": login_url,
    }

    body_html = render_to_string("email/recuperacao_senha.html", context)
    body_text = render_to_string("email/recuperacao_senha.txt", context)

    subject = "Sua nova senha temporária — Clama"
    email = EmailMultiAlternatives(
        subject=subject,
        body=body_text,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[email_destino],
        reply_to=["contato@clama.me"],
    )
    email.attach_alternative(body_html, "text/html")
    email.send()

    dominio = email_destino.rsplit("@", 1)[-1] if "@" in email_destino else "?"
    logger.info(
        "Email de recuperação de senha enviado",
        extra={
            "event": "email_recuperacao_senha_sent",
            "email_dominio": dominio,
        },
    )
