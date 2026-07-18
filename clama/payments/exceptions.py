"""
Exceções do app payments.
"""

from clama.core.exceptions import ClamaBaseException


class PaymentProviderError(ClamaBaseException):
    """
    Erro de integração com o gateway de pagamento (agnóstico de provider).

    Levantado quando uma operação no gateway falha após esgotar os retries.
    Superfície agnóstica de provider para que views/tasks não
    precisem saber qual gateway está em uso.

    Attributes:
        upstream_status: HTTP status devolvido pelo gateway (None se rede/timeout).
        upstream_body: Corpo da resposta do gateway (dict ou str truncada).
    """

    code = "payment_provider_error"
    message = "Erro de integração com o serviço de pagamento"
    pastoral_message = "Tivemos um soluço com o pagamento. Pode tentar novamente em instantes."

    def __init__(
        self,
        message=None,
        code=None,
        pastoral_message=None,
        upstream_status: int | None = None,
        upstream_body=None,
        extra=None,
    ):
        super().__init__(message, code, pastoral_message, extra)
        self.upstream_status = upstream_status
        self.upstream_body = upstream_body
