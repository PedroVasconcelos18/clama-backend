"""
Testes para `is_disposable` (lista estática de domínios descartáveis).
"""

import pytest

from clama.freemium.services.email_blacklist import is_disposable


@pytest.mark.parametrize(
    "email",
    [
        "user@mailinator.com",
        "USER@MAILINATOR.COM",
        "  user@guerrillamail.com  ",
        "alice@10minutemail.com",
        "bob@tempmail.com",
        "carol@yopmail.com",
        "dan@trashmail.com",
        "eve@throwawaymail.com",
        "user@maildrop.cc",
        "user@1secmail.com",
    ],
)
def test_emails_descartaveis_detectados(email):
    assert is_disposable(email) is True


@pytest.mark.parametrize(
    "email",
    [
        "alice@gmail.com",
        "bob@outlook.com",
        "carol@hotmail.com",
        "dan@example.com",
        "user@empresa.com.br",
    ],
)
def test_emails_legitimos_passam(email):
    assert is_disposable(email) is False


@pytest.mark.parametrize("email", ["", "sem-arroba", "@semdominio", "user@"])
def test_inputs_invalidos_retornam_false(email):
    # Validação de formato é responsabilidade do serializer; este serviço
    # tolera lixo retornando False.
    assert is_disposable(email) is False
