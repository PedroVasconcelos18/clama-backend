"""
Exceções customizadas do app freemium.

Convenções:
- `BlacklistHitError`: CPF/email/telefone já usaram o pedido gratuito.
  409 pastoral. (Telefone re-adicionado em 2026-05-10.)
- `EmailDescartavelError`: e-mail é de provedor temporário/descartável.
  400 pastoral.
- `ConfirmationTokenInvalidoError` / `ConfirmationTokenExpiradoError`:
  token de confirmação por e-mail (double opt-in) não confere ou expirou.
  400 pastoral em ambos os casos.
- `TurnstileInvalidoError`: token Cloudflare Turnstile rejeitado. 400 pastoral.
- `UserJaPossuiContaError`: gate user-existence na submissão freemium —
  user já tem conta. 409 com `redirect: "/login"`.
- `PedidoEmAndamentoError`: gate de pedido pendente (resubmit antes da
  confirmação por email). 409 sem redirect (toast pastoral no front).
"""

from clama.core.exceptions import PastoralAPIException
from clama.core.pastoral_messages import (
    MSG_FREEMIUM_BLACKLIST_HIT,
    MSG_FREEMIUM_EMAIL_DESCARTAVEL,
    MSG_FREEMIUM_PEDIDO_EM_ANDAMENTO,
    MSG_FREEMIUM_USER_JA_POSSUI_CONTA,
)


class BlacklistHitError(PastoralAPIException):
    """CPF/email já consumiu o pedido gratuito."""

    status_code = 409
    code = "freemium_blacklist_hit"
    message = "Identificador já usou o pedido gratuito"
    pastoral_message = MSG_FREEMIUM_BLACKLIST_HIT


class EmailDescartavelError(PastoralAPIException):
    """E-mail informado é de provedor temporário/descartável."""

    status_code = 400
    code = "email_descartavel"
    message = "E-mail descartável não permitido"
    pastoral_message = MSG_FREEMIUM_EMAIL_DESCARTAVEL


class ConfirmationTokenInvalidoError(PastoralAPIException):
    """Token de confirmação não existe ou já foi consumido (single-use)."""

    status_code = 400
    code = "confirmation_token_invalido"
    message = "Token de confirmação inválido ou já utilizado"
    pastoral_message = (
        "Esse link não é mais válido. Faça um novo pedido."
    )


class ConfirmationTokenExpiradoError(PastoralAPIException):
    """Token de confirmação existe mas o TTL de 24h passou."""

    status_code = 400
    code = "confirmation_token_expirado"
    message = "Token de confirmação expirado"
    pastoral_message = (
        "Esse link expirou. Faça um novo pedido pra receber sua oração grátis."
    )


class TurnstileInvalidoError(PastoralAPIException):
    """Token do Cloudflare Turnstile não passou na verificação anti-robô."""

    status_code = 400
    code = "captcha_invalido"
    message = "Token Turnstile inválido"
    pastoral_message = (
        "Verificação anti-robô falhou. Atualize a página e tente de novo."
    )


class UserJaPossuiContaError(PastoralAPIException):
    """
    User-existence gate hit na submissão freemium.

    Algum dos identificadores (email, email_hash, cpf_hash, telefone_hash)
    bate com um User existente — provavelmente criado pela saga G1
    anterior. Frontend deve seguir o `redirect` pra `/login` e exibir a
    `pastoral_message` como flash.
    """

    status_code = 409
    code = "user_ja_possui_conta"
    message = "User já tem conta — redirect para /login"
    pastoral_message = MSG_FREEMIUM_USER_JA_POSSUI_CONTA

    def __init__(self):
        super().__init__(extra={"redirect": "/login"})


class PedidoEmAndamentoError(PastoralAPIException):
    """
    Pedido pendente (`AGUARDANDO_CONFIRMACAO_EMAIL`) com mesmos
    identificadores. Resubmissão duplicada — 409 sem redirect, frontend
    mostra toast pastoral.
    """

    status_code = 409
    code = "pedido_em_andamento"
    message = "Pedido pendente aguardando confirmação por e-mail"
    pastoral_message = MSG_FREEMIUM_PEDIDO_EM_ANDAMENTO
