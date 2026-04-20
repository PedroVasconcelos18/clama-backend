"""
Exceções do app prayer_generation.
"""

from clama.core.exceptions import ClamaBaseException


class PrayerGenerationError(ClamaBaseException):
    """
    Erro na geração de oração.

    Levantado quando a geração via Claude API falha após
    esgotar todas as tentativas de retry.
    """

    code = "prayer_generation_error"
    message = "Erro na geração da oração"
    pastoral_message = "A oração precisou de mais um instante. Vamos tentar de novo logo."


class InsufficientCreditsError(PrayerGenerationError):
    """
    Anthropic retornou erro de saldo/créditos insuficientes.

    É uma falha persistente: só resolve quando o admin recarrega créditos.
    Não deve ser reagendada pelo Celery — o pedido fica em ERRO e aguarda
    intervenção manual via endpoint admin de reenviar.
    """

    code = "anthropic_no_credits"
    message = "Créditos insuficientes na API da Anthropic"
