"""
Exceções do app notifications.
"""

from clama.core.exceptions import ClamaBaseException


class WhatsAppIntegrationError(ClamaBaseException):
    """Erro de integração com provider WhatsApp (Z-API, Twilio, etc.)."""

    code = "whatsapp_failed"
    message = "Falha ao enviar WhatsApp"
    pastoral_message = (
        "O envio pelo WhatsApp não foi possível agora. "
        "Vamos tentar de novo logo."
    )


class EmailIntegrationError(ClamaBaseException):
    """Erro de integração com provider de email (Resend)."""

    code = "email_failed"
    message = "Falha ao enviar email"
    pastoral_message = (
        "O envio do email não foi possível agora. "
        "Vamos tentar de novo logo."
    )
