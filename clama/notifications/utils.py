"""
Utilitários para notificações.
"""

import re


def format_telefone_e164(raw: str) -> str:
    """
    Converte telefone brasileiro para formato E.164 (+55XXXXXXXXXXX).

    Args:
        raw: Telefone em qualquer formato comum
            Ex: "(11) 98888-7777", "11988887777", "+5511988887777"

    Returns:
        Telefone no formato E.164: "+5511988887777"

    Raises:
        ValueError: Se telefone for vazio ou inválido
    """
    if not raw:
        raise ValueError("Telefone vazio")

    # Remove todos os caracteres não-numéricos
    digits = re.sub(r"\D", "", raw)

    # Remove prefixo 55 se já existir
    if digits.startswith("55") and len(digits) > 11:
        digits = digits[2:]

    # Valida comprimento (10 = fixo, 11 = celular com nono dígito)
    if len(digits) not in (10, 11):
        raise ValueError(f"Telefone inválido: {raw}")

    # Monta formato E.164
    formatted = f"+55{digits}"

    # Validação final via regex
    if not re.fullmatch(r"\+55\d{10,11}", formatted):
        raise ValueError(f"Telefone inválido: {raw}")

    return formatted


def format_telefone_zapi(e164: str) -> str:
    """
    Converte telefone E.164 para formato Z-API (sem o +).

    Args:
        e164: Telefone no formato E.164 (+5511988887777)

    Returns:
        Telefone sem o +: "5511988887777"
    """
    return e164.lstrip("+")
