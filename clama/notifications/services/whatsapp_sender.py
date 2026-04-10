"""
Protocol para envio de mensagens via WhatsApp.

Permite implementações intercambiáveis (Z-API, Twilio, etc.)
sem alterar código consumidor.
"""

from typing import Protocol


class WhatsAppSender(Protocol):
    """
    Protocol para envio de mensagens WhatsApp.

    Implementações devem retornar dict com:
    - provider_message_id: str - ID da mensagem no provider

    O caller persiste esse ID em `Pedido.whatsapp_message_id`
    para tracking de entrega.
    """

    def send(self, telefone: str, mensagem: str) -> dict:
        """
        Envia mensagem de texto via WhatsApp.

        Args:
            telefone: Número no formato E.164 (+5511999999999)
            mensagem: Texto da mensagem

        Returns:
            dict com provider_message_id: str

        Raises:
            ValueError: Se telefone não estiver no formato E.164
            WhatsAppIntegrationError: Se envio falhar após retries
        """
        ...
