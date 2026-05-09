"""
Validadores de CPF/CNPJ (algoritmo de dígito verificador).

Porte direto de `clama-frontend/src/lib/validators/cpfCnpj.ts` para manter
paridade entre validação de cliente e servidor.

Funções públicas:
- `is_valid_cpf(digits: str) -> bool`
- `is_valid_cnpj(digits: str) -> bool`
- `validar_documento(value: str) -> str`: normaliza e valida CPF/CNPJ;
  retorna apenas dígitos. Levanta `ValueError` com mensagem pastoral.
"""


def is_valid_cpf(digits: str) -> bool:
    """
    Valida CPF com dígito verificador.

    Espera string de 11 dígitos (sem máscara).
    """
    if len(digits) != 11 or not digits.isdigit():
        return False
    # Rejeita sequências repetidas (000.000.000-00, 111..., etc.)
    if digits == digits[0] * 11:
        return False

    soma = sum(int(digits[i]) * (10 - i) for i in range(9))
    dv1 = (soma * 10) % 11
    if dv1 == 10:
        dv1 = 0
    if dv1 != int(digits[9]):
        return False

    soma = sum(int(digits[i]) * (11 - i) for i in range(10))
    dv2 = (soma * 10) % 11
    if dv2 == 10:
        dv2 = 0
    return dv2 == int(digits[10])


def is_valid_cnpj(digits: str) -> bool:
    """
    Valida CNPJ com dígito verificador.

    Espera string de 14 dígitos (sem máscara).
    """
    if len(digits) != 14 or not digits.isdigit():
        return False
    # Rejeita sequências repetidas (00.000.000/0000-00, etc.)
    if digits == digits[0] * 14:
        return False

    pesos1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    pesos2 = [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]

    soma1 = sum(int(digits[i]) * pesos1[i] for i in range(12))
    dv1 = soma1 % 11
    dv1 = 0 if dv1 < 2 else 11 - dv1
    if dv1 != int(digits[12]):
        return False

    soma2 = sum(int(digits[i]) * pesos2[i] for i in range(13))
    dv2 = soma2 % 11
    dv2 = 0 if dv2 < 2 else 11 - dv2
    return dv2 == int(digits[13])


def normalizar_documento(value: str) -> str:
    """Mantém apenas dígitos do CPF/CNPJ."""
    return "".join(c for c in (value or "") if c.isdigit())


def validar_documento(value: str) -> str:
    """
    Normaliza e valida CPF/CNPJ. Retorna apenas dígitos.

    Levanta `ValueError` com mensagem pastoral se inválido.
    """
    digits = normalizar_documento(value)

    if len(digits) == 11:
        if not is_valid_cpf(digits):
            raise ValueError("Confira seu CPF — parece que tem algum dígito errado.")
        return digits
    if len(digits) == 14:
        if not is_valid_cnpj(digits):
            raise ValueError("Confira seu CNPJ — parece que tem algum dígito errado.")
        return digits

    raise ValueError("CPF deve ter 11 dígitos ou CNPJ deve ter 14 dígitos.")
