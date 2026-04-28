"""
Cliente wrapper para a API Anthropic (Claude).

Suporta inclusão de documentos de contexto via Files API.
"""

import logging
import time

import anthropic
from django.conf import settings

from clama.core.retry import with_retry
from clama.orders.models import Pedido
from clama.prayer_generation.exceptions import (
    InsufficientCreditsError,
    PrayerGenerationError,
)
from clama.prayer_generation.services.prompt_builder import build_prompt
from clama.prompts.models import PromptTemplate

logger = logging.getLogger("clama.prayer_generation.anthropic_client")

# Modelo Claude para geração de orações
MODEL_NAME = "claude-sonnet-4-20250514"
MAX_TOKENS = 1500
REQUEST_TIMEOUT = 30.0

# Beta header para Files API
FILES_API_BETA_HEADER = "files-api-2025-04-14"

# API keys que indicam modo mock (sem créditos ou não configurado)
MOCK_API_KEYS = {"", "test_api_key_for_local_development"}

# Oração mock para desenvolvimento/testes
MOCK_PRAYER_TEMPLATE = """Senhor, venho diante de Ti em nome de {nome}.

Tu conheces cada detalhe da vida dela, cada angústia e cada esperança que habita seu coração. Neste momento, ela clama por Tua intervenção, e eu sei que Tu ouves.

Pai, derrama Tua paz sobre {nome}. Que ela sinta Tua presença de forma real e tangível. Onde há medo, coloca coragem. Onde há dúvida, firma a fé. Onde há dor, traz o bálsamo do Teu amor.

Guia seus passos, ilumina seu caminho e dá-lhe sabedoria para cada decisão. Que ela encontre descanso em Ti, sabendo que Tu és fiel para cumprir Tuas promessas.

Em nome de Jesus, amém.

---
[MODO DESENVOLVIMENTO: Esta é uma oração de exemplo. Configure ANTHROPIC_API_KEY com créditos para gerar orações personalizadas via IA.]"""


class AnthropicClient:
    """
    Cliente para integração com a API Anthropic (Claude).

    Implementa retry automático para erros de rede e overload (529).
    Todos os métodos logam eventos estruturados sem PII.

    Em modo mock (sem API key válida), retorna oração de exemplo para
    permitir testes do fluxo completo sem créditos na Anthropic.
    """

    def __init__(self):
        """
        Inicializa o cliente com credenciais do settings.
        """
        api_key = settings.ANTHROPIC_API_KEY or ""
        self.mock_mode = api_key in MOCK_API_KEYS

        if self.mock_mode:
            logger.info(
                "AnthropicClient em modo mock",
                extra={"event": "anthropic_mock_mode", "reason": "no_valid_api_key"},
            )
            self.client = None
        else:
            self.client = anthropic.Anthropic(api_key=api_key)

    def _get_documentos_contexto(self) -> list[dict]:
        """
        Retorna lista de document blocks para documentos ativos e sincronizados.

        Returns:
            Lista de dicts no formato esperado pela API (document blocks com file_id)
        """
        from clama.documents.models import DocumentoContexto

        documentos = DocumentoContexto.objects.ativos_sincronizados()
        blocks = []

        for doc in documentos:
            blocks.append({
                "type": "document",
                "source": {
                    "type": "file",
                    "file_id": doc.anthropic_file_id,
                },
                "cache_control": {"type": "ephemeral"},
            })

        if blocks:
            logger.info(
                "Documentos de contexto incluídos",
                extra={
                    "event": "documentos_contexto_incluidos",
                    "count": len(blocks),
                    "file_ids": [doc.anthropic_file_id for doc in documentos],
                },
            )

        return blocks

    def _get_mock_prayer(self, nome: str) -> str:
        """Retorna oração mock para desenvolvimento."""
        return MOCK_PRAYER_TEMPLATE.format(nome=nome)

    def _log_request(
        self,
        model: str,
        plano_complexidade: str,
        attempt: int,
        duration_ms: float,
        tokens_used: int | None = None,
        cache_creation_tokens: int | None = None,
        cache_read_tokens: int | None = None,
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
        if cache_creation_tokens is not None:
            log_data["cache_creation_tokens"] = cache_creation_tokens
        if cache_read_tokens is not None:
            log_data["cache_read_tokens"] = cache_read_tokens
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
        # Modo mock: retorna oração de exemplo
        if self.mock_mode:
            primeiro_nome = pedido.nome.split()[0] if pedido.nome else "irmã"
            logger.info(
                "Retornando oração mock",
                extra={"event": "anthropic_mock_prayer", "pedido_id": str(pedido.id)},
            )
            return self._get_mock_prayer(primeiro_nome)

        # Busca template ativo
        template = PromptTemplate.objects.get_active()

        # Monta prompt
        system_prompt, user_message = build_prompt(pedido, template)

        # Busca documentos de contexto ativos e sincronizados
        documentos_blocks = self._get_documentos_contexto()

        # Monta conteúdo da mensagem do usuário
        # Se há documentos de contexto, inclui como document blocks antes do texto
        if documentos_blocks:
            user_content = documentos_blocks + [{"type": "text", "text": user_message}]
        else:
            user_content = user_message

        start_time = time.time()
        try:
            # Usa beta header se há documentos de contexto
            extra_headers = {}
            if documentos_blocks:
                extra_headers["anthropic-beta"] = FILES_API_BETA_HEADER

            response = self.client.messages.create(
                model=MODEL_NAME,
                max_tokens=MAX_TOKENS,
                system=[
                    {
                        "type": "text",
                        "text": system_prompt,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                messages=[{"role": "user", "content": user_content}],
                timeout=REQUEST_TIMEOUT,
                extra_headers=extra_headers if extra_headers else None,
            )
            duration_ms = (time.time() - start_time) * 1000

            # Extrai texto e métricas
            text = response.content[0].text
            tokens_used = response.usage.output_tokens
            cache_creation_tokens = getattr(
                response.usage, "cache_creation_input_tokens", None
            )
            cache_read_tokens = getattr(
                response.usage, "cache_read_input_tokens", None
            )

            self._log_request(
                model=MODEL_NAME,
                plano_complexidade=pedido.plano.complexidade,
                attempt=1,
                duration_ms=duration_ms,
                tokens_used=tokens_used,
                cache_creation_tokens=cache_creation_tokens,
                cache_read_tokens=cache_read_tokens,
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

            # Créditos insuficientes: propaga como erro persistente
            # (tratado em tasks.py sem reagendamento + mensagem pastoral 24h)
            if e.status_code == 400 and "credit balance" in str(e.message).lower():
                logger.warning(
                    "Anthropic sem créditos",
                    extra={"event": "anthropic_no_credits", "pedido_id": str(pedido.id)},
                )
                raise InsufficientCreditsError(
                    message=f"Anthropic sem créditos: {e.message}"
                ) from e

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

    def _generate_raw(self, system_prompt: str, user_message: str, nome: str = "irmã") -> str:
        """
        Gera texto usando Claude diretamente (para preview admin).

        Args:
            system_prompt: System prompt completo
            user_message: User message completo
            nome: Nome para personalizar oração mock (default: "irmã")

        Returns:
            Texto gerado

        Raises:
            PrayerGenerationError: Se a geração falhar
        """
        # Modo mock: retorna oração de exemplo
        if self.mock_mode:
            logger.info(
                "Retornando preview mock",
                extra={"event": "anthropic_mock_preview"},
            )
            return self._get_mock_prayer(nome)

        start_time = time.time()
        try:
            response = self.client.messages.create(
                model=MODEL_NAME,
                max_tokens=MAX_TOKENS,
                system=[
                    {
                        "type": "text",
                        "text": system_prompt,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
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

        except anthropic.APIStatusError as e:
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
            # Créditos insuficientes: propaga como erro persistente
            if e.status_code == 400 and "credit balance" in str(e.message).lower():
                logger.warning(
                    "Anthropic sem créditos (preview)",
                    extra={"event": "anthropic_no_credits_preview"},
                )
                raise InsufficientCreditsError(
                    message=f"Anthropic sem créditos: {e}"
                ) from e

            raise PrayerGenerationError(
                message=f"Erro ao gerar preview: {e}"
            ) from e

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
