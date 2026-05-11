"""
Fixtures comuns dos testes do app customers.

Auto-limpa cache antes/depois de cada teste — sem isso, throttles
(`customer_login`, `customer_change_password`) acumulam estado entre tests
sequenciais (todos compartilham o mesmo IP cliente) e fazem testes do
`TestCustomerLogout` / `TestChangePassword` baterem em 429 antes do login
completar.
"""

import pytest
from django.core.cache import cache


@pytest.fixture(autouse=True)
def _clear_cache_around_each_test():
    cache.clear()
    yield
    cache.clear()
