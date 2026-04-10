"""
Testes para os helpers de moeda do Clama.
"""
from decimal import Decimal

import pytest

from clama.core.money import centavos_to_reais_str, reais_to_centavos


class TestReaisToCentavos:
    """Testes para conversão de reais para centavos."""

    def test_float_20_returns_2000(self):
        """20.00 reais deve retornar 2000 centavos."""
        assert reais_to_centavos(20.00) == 2000

    def test_float_19_99_returns_1999(self):
        """19.99 reais deve retornar 1999 centavos."""
        assert reais_to_centavos(19.99) == 1999

    def test_string_value(self):
        """String '19.99' deve retornar 1999 centavos."""
        assert reais_to_centavos("19.99") == 1999

    def test_decimal_value(self):
        """Decimal('100.50') deve retornar 10050 centavos."""
        assert reais_to_centavos(Decimal("100.50")) == 10050

    def test_integer_value(self):
        """Inteiro 10 deve retornar 1000 centavos."""
        assert reais_to_centavos(10) == 1000

    def test_zero(self):
        """Zero deve retornar 0 centavos."""
        assert reais_to_centavos(0) == 0


class TestCentavosToReaisStr:
    """Testes para conversão de centavos para string formatada."""

    def test_zero_returns_formatted(self):
        """0 centavos deve retornar 'R$ 0,00'."""
        assert centavos_to_reais_str(0) == "R$ 0,00"

    def test_2000_returns_formatted(self):
        """2000 centavos deve retornar 'R$ 20,00'."""
        assert centavos_to_reais_str(2000) == "R$ 20,00"

    def test_12345_returns_formatted(self):
        """12345 centavos deve retornar 'R$ 123,45'."""
        assert centavos_to_reais_str(12345) == "R$ 123,45"

    def test_single_digit_cents(self):
        """105 centavos deve retornar 'R$ 1,05' (com zero à esquerda)."""
        assert centavos_to_reais_str(105) == "R$ 1,05"

    def test_only_cents(self):
        """99 centavos deve retornar 'R$ 0,99'."""
        assert centavos_to_reais_str(99) == "R$ 0,99"
