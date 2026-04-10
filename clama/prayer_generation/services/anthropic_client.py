"""
Cliente wrapper para a API Anthropic (Claude).
"""

import logging
import time

import anthropic
from django.conf import settings

from clama.core.retry import with_retry
from clama.orders.models import Pedido
from clama.prayer_generation.exceptions import PrayerGenerationError
from clama.prayer_generation.services.prompt_builder import build_prompt
from clama.prompts.models import PromptTemplate

logger = logging.getLogger("clama.prayer_generation.anthropic_client")

# Modelo Claude para geração de orações
MODEL_NAME = "claude-sonnet-4-20250514"
MAX_TOKENS = 1500
REQUEST_TIMEOUT = 30.0


class AnthropicClient:
    """
    Cliente para integração com a API Anthropic (Claude).

    Implementa retry automático para erros de rede e overload (529).
    Todos os métodos logam eventos estruturados sem PII.
    """

    def __init__(self):
        """
        Inicializa o cliente com credenciais do settings.
        """
        self.client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)

    def _log_request(
        self,
        model: str,
        plano_complexidade: str,
        attempt: int,
        duration_ms: float,
        tokens_used: int | None = None,
        error: str | None = None,
    ) -> None:
        """Loga requisição estruturada (sem PII)."""
        log_data = {
            "event": "anthropic_request",
            "model": model,
            "plano": plano_complexidade,
            "attempt": attempt,
            "duration_ms": round(duration_ms, 2),
        }
        if tokens_used is not None:
            log_data["tokens_used"] = tokens_used
        if error:
            log_data["error"] = error

        if error:
            logger.warning("Anthropic request failed", extra=log_data)
        else:
            logger.info("Anthropic request completed", extra=log_data)

    @with_retry(
        max_attempts=3,
        backoff_seconds=[1, 2, 4],
        retriable_exceptions=(
            anthropic.APIConnectionError,
            anthropic.APITimeoutError,
        ),
        retriable_status_codes=[529],
    )
    def gerar_oracao(self, pedido: Pedido) -> str:
        """
        Gera oração personalizada para o pedido.

        Args:
            pedido: Pedido de oração

        Returns:
            Texto da oração gerada

        Raises:
            PrayerGenerationError: Se a geração falhar após retries
        """
        # Busca template ativo
        template = PromptTemplate.objects.get_active()

        # Monta prompt
        system_prompt, user_message = build_prompt(pedido, template)

        start_time = time.time()
        try:
            response = self.client.messages.create(
                model=MODEL_NAME,
                max_tokens=MAX_TOKENS,
                system=system_prompt,
                messages=[{"role": "user", "content": user_message}],
                timeout=REQUEST_TIMEOUT,
            )
            duration_ms = (time.time() - start_time) * 1000

            # Extrai texto e métricas
            text = response.content[0].text
            tokens_used = response.usage.output_tokens

            self._log_request(
                model=MODEL_NAME,
                plano_complexidade=pedido.plano.complexidade,
                attempt=1,
                duration_ms=duration_ms,
                tokens_used=tokens_used,
            )

            return text

        except (anthropic.APIConnectionError, anthropic.APITimeoutError) as e:
            duration_ms = (time.time() - start_time) * 1000
            self._log_request(
                model=MODEL_NAME,
                plano_complexidade=pedido.plano.complexidade,
                attempt=1,
                duration_ms=duration_ms,
                error=str(e),
            )
            raise  # Será retentado pelo decorator

        except anthropic.APIStatusError as e:
            duration_ms = (time.time() - start_time) * 1000
            self._log_request(
                model=MODEL_NAME,
                plano_complexidade=pedido.plano.complexidade,
                attempt=1,
                duration_ms=duration_ms,
                error=f"HTTP {e.status_code}: {e.message}",
            )
            if e.status_code == 529:
                raise  # Será retentado pelo decorator (overload)
            raise PrayerGenerationError(
                message=f"Erro ao gerar oração: {e.message}"
            ) from e

        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            self._log_request(
                model=MODEL_NAME,
                plano_complexidade=pedido.plano.complexidade,
                attempt=1,
                duration_ms=duration_ms,
                error=str(e),
            )
            raise PrayerGenerationError(
                message=f"Erro inesperado ao gerar oração: {e}"
            ) from e

    def _generate_raw(self, system_prompt: str, user_message: str) -> str:
        """
        Gera texto usando Claude diretamente (para preview admin).

        Args:
            system_prompt: System prompt completo
            user_message: User message completo

        Returns:
            Texto gerado

        Raises:
            PrayerGenerationError: Se a geração falhar
        """
        start_time = time.time()
        try:
            response = self.client.messages.create(
                model=MODEL_NAME,
                max_tokens=MAX_TOKENS,
                system=system_prompt,
                messages=[{"role": "user", "content": user_message}],
                timeout=REQUEST_TIMEOUT,
            )
            duration_ms = (time.time() - start_time) * 1000

            text = response.content[0].text
            tokens_used = response.usage.output_tokens

            logger.info(
                "Anthropic preview request completed",
                extra={
                    "event": "anthropic_preview",
                    "model": MODEL_NAME,
                    "duration_ms": round(duration_ms, 2),
                    "tokens_used": tokens_used,
                },
            )

            return text

        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            logger.warning(
                "Anthropic preview request failed",
                extra={
                    "event": "anthropic_preview",
                    "model": MODEL_NAME,
                    "duration_ms": round(duration_ms, 2),
                    "error": str(e),
                },
            )
            raise PrayerGenerationError(
                message=f"Erro ao gerar preview: {e}"
            ) from e
