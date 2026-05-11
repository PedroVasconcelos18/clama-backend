"""
Fixtures comuns dos testes do app freemium.

- Mock TurnstileClient sempre-válido (default).
- Silencia despachos de Celery do fluxo freemium (`enviar_email_confirmacao_freemium_task`
  e `gerar_oracao_task`) para que os testes possam afirmar sobre `.delay`
  sem efeitos colaterais.
"""

from unittest.mock import patch

import pytest
from django.core.cache import cache


@pytest.fixture(autouse=True)
def _clear_cache_around_each_test():
    """Limpa o cache antes/depois de cada teste para isolar caches/rate-limits."""
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def turnstile_sempre_valido():
    """
    Patch global do `TurnstileClient.validate` para sempre retornar True.

    Útil em testes que querem cobrir o caminho happy path sem se preocupar
    com a presença/ausência de `TURNSTILE_SECRET_KEY`. O mock_mode default
    do client (secret vazio) já aceita qualquer token não-vazio, então em
    quase todos os testes basta mandar um token "qualquer-coisa". Esta
    fixture é para os testes que querem isolar do componente.
    """
    with patch(
        "clama.freemium.api.views.TurnstileClient.validate",
        return_value=True,
    ) as mocked:
        yield mocked


@pytest.fixture
def turnstile_invalido():
    """Patch que força `TurnstileClient.validate` a retornar False."""
    with patch(
        "clama.freemium.api.views.TurnstileClient.validate",
        return_value=False,
    ) as mocked:
        yield mocked


@pytest.fixture(autouse=True)
def _silencia_email_confirmacao_freemium_task():
    """
    Silencia `enviar_email_confirmacao_freemium_task.delay` em todos os
    testes do app — evita disparar e-mail real / depender da fila.

    Os testes que precisam afirmar sobre o `.delay` patcham localmente
    via `with patch(...)`.
    """
    with patch(
        "clama.notifications.tasks.enviar_email_confirmacao_freemium_task.delay",
        return_value=None,
    ) as mocked:
        yield mocked


@pytest.fixture(autouse=True)
def _silencia_gerar_oracao_task():
    """
    Silencia `gerar_oracao_task.delay` em todos os testes do app — evita
    disparar Anthropic / chamadas externas indesejadas. Tests que
    asseveram a chamada patcham localmente.
    """
    with patch(
        "clama.freemium.api.views.gerar_oracao_task.delay",
        return_value=None,
    ) as mocked:
        yield mocked
