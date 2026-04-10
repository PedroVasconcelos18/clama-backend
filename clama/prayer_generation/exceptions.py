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
