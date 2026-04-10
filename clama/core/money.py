"""
Helpers de moeda para o Clama.

Convenção: valores monetários são armazenados em centavos (int) no banco de dados e na API.
Conversão para string com formato "R$ XX,YY" é feita apenas na camada de apresentação.
"""
from decimal import Decimal, ROUND_DOWN


def reais_to_centavos(value) -> int:
    """
    Converte um valor em reais (Decimal, float, str ou int) para centavos (int).

    Args:
        value: Valor em reais (ex: 20.00, "19.99", Decimal("100.50"))

    Returns:
        Valor em centavos como inteiro (ex: 2000, 1999, 10050)

    Examples:
        >>> reais_to_centavos(20.00)
        2000
        >>> reais_to_centavos("19.99")
        1999
        >>> reais_to_centavos(Decimal("100.50"))
        10050
    """
    if isinstance(value, int):
        return value * 100

    decimal_value = Decimal(str(value))
    centavos = decimal_value * 100
    return int(centavos.quantize(Decimal("1"), rounding=ROUND_DOWN))


def centavos_to_reais_str(centavos: int) -> str:
    """
    Converte um valor em centavos para string formatada em reais.

    Args:
        centavos: Valor em centavos (ex: 2000, 1999, 12345)

    Returns:
        String formatada no padrão brasileiro "R$ XX,YY"

    Examples:
        >>> centavos_to_reais_str(0)
        'R$ 0,00'
        >>> centavos_to_reais_str(2000)
        'R$ 20,00'
        >>> centavos_to_reais_str(12345)
        'R$ 123,45'
    """
    reais = centavos // 100
    cents = centavos % 100
    return f"R$ {reais},{cents:02d}"
