"""
Exceções customizadas do app freemium.

Convenções:
- `InfosimplesError`: erro técnico bruto (rede / 5xx esgotado). Não vai
  direto para o usuário; a view captura e converte em 503 pastoral.
- `DocumentoInativoError`: CPF/CNPJ válido no algoritmo mas inativo na
  Receita (SUSPENSO, CANCELADO, INEXISTENTE). 400 pastoral.
- `BlacklistHitError`: CPF/email já usaram o pedido gratuito.
  409 pastoral.
- `EmailDescartavelError`: e-mail é de provedor temporário/descartável.
  400 pastoral.
- `ConfirmationTokenInvalidoError` / `ConfirmationTokenExpiradoError`:
  token de confirmação por e-mail (double opt-in) não confere ou expirou.
  400 pastoral em ambos os casos.
- `TurnstileInvalidoError`: token Cloudflare Turnstile rejeitado. 400 pastoral.
"""

from clama.core.exceptions import ClamaBaseException, PastoralAPIException
from clama.core.pastoral_messages import (
    MSG_FREEMIUM_BLACKLIST_HIT,
    MSG_FREEMIUM_DOCUMENTO_INATIVO,
    MSG_FREEMIUM_EMAIL_DESCARTAVEL,
    MSG_FREEMIUM_INFOSIMPLES_INDISPONIVEL,
)


class InfosimplesError(ClamaBaseException):
    """
    Erro técnico ao consultar a Infosimples (rede, timeout, 5xx esgotado).

    Não é uma `PastoralAPIException` porque não é de uso direto na view —
    a view captura e converte em 503 pastoral controladamente.
    """

    code = "infosimples_error"
    message = "Falha ao consultar Infosimples"
    pastoral_message = MSG_FREEMIUM_INFOSIMPLES_INDISPONIVEL


class InfosimplesIndisponivelError(PastoralAPIException):
    """
    Versão "pastoral" do erro Infosimples — usada na view quando o
    serviço externo está fora do ar para retornar 503 ao usuário.
    """

    status_code = 503
    code = "infosimples_indisponivel"
    message = "Serviço de validação indisponível"
    pastoral_message = MSG_FREEMIUM_INFOSIMPLES_INDISPONIVEL


class DocumentoInativoError(PastoralAPIException):
    """CPF/CNPJ inativo na Receita (SUSPENSO, CANCELADO, INEXISTENTE)."""

    status_code = 400
    code = "documento_inativo"
    message = "CPF/CNPJ não está ativo na Receita"
    pastoral_message = MSG_FREEMIUM_DOCUMENTO_INATIVO


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
