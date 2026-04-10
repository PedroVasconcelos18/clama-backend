"""
Exceções do app payments.
"""

from clama.core.exceptions import ClamaBaseException


class AsaasIntegrationError(ClamaBaseException):
    """
    Erro de integração com a API do Asaas.

    Levantado quando uma operação na API do Asaas falha após
    esgotar todas as tentativas de retry.
    """

    code = "asaas_integration_error"
    message = "Erro de integração com o serviço de pagamento"
    pastoral_message = "Tivemos um soluço com o pagamento. Pode tentar novamente em instantes."
