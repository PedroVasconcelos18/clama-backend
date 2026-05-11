"""
Exceções personalizadas do Clama com mensagens pastorais.

Toda resposta de erro da API Clama segue o formato:
{
    "error": {
        "code": "nome_curto",
        "message": "mensagem técnica",
        "pastoral_message": "mensagem acolhedora para a usuária"
    }
}
"""
from rest_framework.exceptions import APIException


class ClamaBaseException(Exception):
    """
    Exceção base do Clama com suporte a mensagens pastorais.

    `extra` é um dict opcional cujas chaves são mergidas no body do erro
    pelo handler — útil pra propagar hints estruturados (ex.: `redirect`)
    pro frontend sem inflar a interface da exception.
    """

    code: str = "clama_error"
    message: str = "Erro"
    pastoral_message: str = "Algo não saiu como o esperado."

    def __init__(self, message=None, code=None, pastoral_message=None, extra=None):
        self.message = message or self.message
        self.code = code or self.code
        self.pastoral_message = pastoral_message or self.pastoral_message
        # `extra` é instance-level — não compartilha entre exceptions.
        self.extra = dict(extra) if extra else {}
        super().__init__(self.message)


class PastoralAPIException(ClamaBaseException, APIException):
    """
    Exceção para uso em views DRF que retorna erro pastoral.
    """

    status_code = 400
    default_detail = "Erro na requisição"
    default_code = "bad_request"

    def __init__(
        self,
        message=None,
        code=None,
        pastoral_message=None,
        status_code=None,
        extra=None,
    ):
        ClamaBaseException.__init__(self, message, code, pastoral_message, extra)
        if status_code:
            self.status_code = status_code
        # Necessário para APIException
        self.detail = self.message
