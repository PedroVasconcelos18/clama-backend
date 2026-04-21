"""
Exceções do app payments.
"""

from clama.core.exceptions import ClamaBaseException


class AsaasIntegrationError(ClamaBaseException):
    """
    Erro de integração com a API do Asaas.

    Levantado quando uma operação na API do Asaas falha após
    esgotar todas as tentativas de retry.

    Attributes:
        upstream_status: HTTP status devolvido pela Asaas (None se rede/timeout).
        upstream_body: Corpo da resposta da Asaas (dict ou str truncada).
    """

    code = "asaas_integration_error"
    message = "Erro de integração com o serviço de pagamento"
    pastoral_message = "Tivemos um soluço com o pagamento. Pode tentar novamente em instantes."

    def __init__(
        self,
        message=None,
        code=None,
        pastoral_message=None,
        upstream_status: int | None = None,
        upstream_body=None,
    ):
        super().__init__(message, code, pastoral_message)
        self.upstream_status = upstream_status
        self.upstream_body = upstream_body
