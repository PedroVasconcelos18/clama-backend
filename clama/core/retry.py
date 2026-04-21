"""
Decorator de retry com backoff exponencial.
"""
import contextvars
import logging
import time
from functools import wraps
from typing import Callable, TypeVar

import requests

logger = logging.getLogger(__name__)

T = TypeVar("T")

_current_attempt: contextvars.ContextVar[int] = contextvars.ContextVar(
    "retry_current_attempt", default=1
)


def get_current_attempt() -> int:
    """Retorna a tentativa atual dentro de uma função decorada com @with_retry."""
    return _current_attempt.get()


def with_retry(
    max_attempts: int = 3,
    backoff_seconds: list[int] | None = None,
    retriable_exceptions: tuple | None = None,
    retriable_status_codes: list[int] | None = None,
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """
    Decorator que adiciona retry automático com backoff exponencial.

    Retenta por padrão em:
    - requests.ConnectionError
    - requests.Timeout
    - HTTP 5xx (requests.HTTPError com status_code >= 500)

    Também retenta em:
    - Exceções adicionais passadas em retriable_exceptions
    - Status codes específicos passados em retriable_status_codes

    Não retenta em:
    - HTTP 4xx (exceto se especificado em retriable_status_codes)
    - Outras exceções (exceto se especificado em retriable_exceptions)

    Args:
        max_attempts: Número máximo de tentativas (default: 3)
        backoff_seconds: Lista de segundos de espera entre tentativas
                        (default: [1, 2, 4])
        retriable_exceptions: Tupla de exceções adicionais que devem ser
                             retentadas (além das padrão do requests)
        retriable_status_codes: Lista de status codes HTTP específicos que
                               devem ser retentados (ex: [429, 529])

    Returns:
        Decorated function
    """
    if backoff_seconds is None:
        backoff_seconds = [1, 2, 4]
    if retriable_exceptions is None:
        retriable_exceptions = ()
    if retriable_status_codes is None:
        retriable_status_codes = []

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args, **kwargs) -> T:
            last_exc: Exception | None = None

            for attempt in range(1, max_attempts + 1):
                _current_attempt.set(attempt)
                try:
                    return func(*args, **kwargs)
                except (requests.ConnectionError, requests.Timeout) as e:
                    last_exc = e
                    logger.warning(
                        "Retry attempt %d/%d due to %s: %s",
                        attempt,
                        max_attempts,
                        type(e).__name__,
                        str(e),
                    )
                except requests.HTTPError as e:
                    if e.response is not None and 500 <= e.response.status_code < 600:
                        last_exc = e
                        logger.warning(
                            "Retry attempt %d/%d due to HTTP %d",
                            attempt,
                            max_attempts,
                            e.response.status_code,
                        )
                    else:
                        # 4xx ou outros erros HTTP não retentam
                        raise
                except retriable_exceptions as e:
                    # Exceções customizadas que devem ser retentadas
                    last_exc = e
                    logger.warning(
                        "Retry attempt %d/%d due to %s: %s",
                        attempt,
                        max_attempts,
                        type(e).__name__,
                        str(e),
                    )
                except Exception as e:
                    # Verifica se é uma exceção com status_code (ex: anthropic.APIStatusError)
                    status_code = getattr(e, "status_code", None)
                    if status_code is not None and status_code in retriable_status_codes:
                        last_exc = e
                        logger.warning(
                            "Retry attempt %d/%d due to status code %d: %s",
                            attempt,
                            max_attempts,
                            status_code,
                            str(e),
                        )
                    else:
                        raise

                # Aguardar antes da próxima tentativa
                if attempt < max_attempts:
                    sleep_time = (
                        backoff_seconds[attempt - 1]
                        if attempt - 1 < len(backoff_seconds)
                        else backoff_seconds[-1]
                    )
                    time.sleep(sleep_time)

            # Se chegou aqui, esgotou as tentativas
            if last_exc is not None:
                raise last_exc
            raise RuntimeError("Retry failed without exception")

        return wrapper

    return decorator
