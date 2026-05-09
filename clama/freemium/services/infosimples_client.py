"""
Cliente para a API da Infosimples — consulta de CPF/CNPJ na Receita Federal.

Ver documentação:
- CPF: https://api.infosimples.com/api/v2/consultas/receita-federal/cpf
- CNPJ: https://api.infosimples.com/api/v2/consultas/receita-federal/cnpj

Mock mode: se `INFOSIMPLES_TOKEN` estiver vazio (default em ambiente de
testes/local), o cliente retorna um payload mockado sem fazer chamada de
rede. Isso espelha o padrão usado no `AnthropicClient`.

Logging: estruturado, sem PII. Documentos são logados apenas com os 4
últimos dígitos.
"""

import logging
import time
from typing import Any

import requests
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from clama.core.retry import get_current_attempt, with_retry
from clama.freemium.exceptions import InfosimplesError
from clama.freemium.hashing import normalizar_cpf_cnpj

logger = logging.getLogger("clama.freemium.infosimples")

REQUEST_TIMEOUT = 15  # segundos
DEFAULT_BASE_URL = "https://api.infosimples.com/api/v2/consultas/receita-federal"

# Tokens que indicam modo mock (não configurado / placeholder).
MOCK_TOKENS = {"", "test_infosimples_token", "test"}

# Status normalizados retornados pelo método consultar_cpf_cnpj.
STATUS_ATIVO = "ATIVO"
STATUS_SUSPENSO = "SUSPENSO"
STATUS_CANCELADO = "CANCELADO"
STATUS_INEXISTENTE = "INEXISTENTE"

# Status considerados inativos — viram DocumentoInativoError 400 pastoral
# quando a view chama consultar_cpf_cnpj.
STATUS_INATIVOS = {STATUS_SUSPENSO, STATUS_CANCELADO, STATUS_INEXISTENTE}


class InfosimplesClient:
    """
    Wrapper sobre a API Infosimples para consulta de CPF/CNPJ.

    Em modo mock retorna `{"status": "ATIVO", "nome": "MOCK PESSOA"}`
    para permitir que o fluxo freemium seja testado sem chamadas externas.
    """

    def __init__(self) -> None:
        token = getattr(settings, "INFOSIMPLES_TOKEN", "") or ""
        self.token = token
        self.mock_mode = token in MOCK_TOKENS
        self.base_url = getattr(
            settings, "INFOSIMPLES_BASE_URL", DEFAULT_BASE_URL
        ).rstrip("/")

        # P-1: Guarda contra mock_mode silencioso em produção. Se o token
        # estiver vazio/placeholder e não estamos em DEBUG nem rodando testes,
        # falhe cedo — caso contrário todo CPF retornaria ATIVO sem qualquer
        # validação real, o que vira oracle pra fraudadores.
        # P-V3 wave 2: substitui heurística "test in sys.argv | pytest in
        # sys.modules" por `settings.TESTING` explícito (False em base, True
        # em test.py). Argumentos como `--test-connection` e k8s liveness
        # probes ativavam mock_mode falso-positivo em produção.
        if self.mock_mode:
            debug = bool(getattr(settings, "DEBUG", False))
            is_test = bool(getattr(settings, "TESTING", False))
            if not debug and not is_test:
                raise ImproperlyConfigured(
                    "INFOSIMPLES_TOKEN obrigatório em produção — "
                    "mock_mode silencioso desabilitado fora de DEBUG/testes."
                )
            logger.info(
                "InfosimplesClient em modo mock",
                extra={"event": "infosimples_mock_mode"},
            )

    @staticmethod
    def _ultimos_4(documento_normalizado: str) -> str:
        return documento_normalizado[-4:] if len(documento_normalizado) >= 4 else "****"

    @staticmethod
    def _is_cnpj(documento_normalizado: str) -> bool:
        return len(documento_normalizado) == 14

    def _endpoint(self, documento_normalizado: str) -> str:
        if self._is_cnpj(documento_normalizado):
            return f"{self.base_url}/cnpj"
        return f"{self.base_url}/cpf"

    def _log(
        self,
        endpoint: str,
        status: int | None,
        duration_ms: float,
        ultimos_4: str,
        error: str | None = None,
    ) -> None:
        log_data = {
            "event": "infosimples_request",
            "endpoint": endpoint,
            "status": status,
            "attempt": get_current_attempt(),
            "duration_ms": round(duration_ms, 2),
            "documento_ultimos_4": ultimos_4,
        }
        if error:
            log_data["error"] = error
        if error or (status and status >= 400):
            logger.warning("Infosimples request failed", extra=log_data)
        else:
            logger.info("Infosimples request completed", extra=log_data)

    def _parse_status(self, payload: dict[str, Any]) -> str:
        """
        Extrai o status normalizado do payload Infosimples.

        Formato esperado (simplificado):
        {
            "code": 200,
            "code_message": "...",
            "data": [{"situacao_cadastral": "REGULAR" | "SUSPENSA" | ...,
                      "nome": "..."}]
        }

        - code 200 + situacao "REGULAR" / "ATIVA" → ATIVO
        - code 200 + situacao "SUSPENSA" → SUSPENSO
        - code 200 + situacao "CANCELADA" / "NULA" / "BAIXADA" → CANCELADO
        - code != 200 (612 = não encontrado etc) → INEXISTENTE
        """
        code = payload.get("code")
        if code != 200:
            return STATUS_INEXISTENTE

        data = payload.get("data") or []
        if not data:
            return STATUS_INEXISTENTE

        primeiro = data[0] if isinstance(data, list) else data
        situacao = (primeiro.get("situacao_cadastral") or "").strip().upper()

        if situacao in {"REGULAR", "ATIVA", "ATIVO"}:
            return STATUS_ATIVO
        if situacao in {"SUSPENSA", "SUSPENSO"}:
            return STATUS_SUSPENSO
        if situacao in {
            "CANCELADA",
            "CANCELADO",
            "NULA",
            "NULO",
            "BAIXADA",
            "BAIXADO",
            "INAPTA",
            "INAPTO",
        }:
            return STATUS_CANCELADO

        # Default: tratar como inexistente para não confiar em situação
        # desconhecida.
        return STATUS_INEXISTENTE

    def _parse_nome(self, payload: dict[str, Any]) -> str | None:
        data = payload.get("data") or []
        if not data:
            return None
        primeiro = data[0] if isinstance(data, list) else data
        nome = primeiro.get("nome") or primeiro.get("razao_social")
        if not nome:
            return None
        return str(nome).strip() or None

    @with_retry(
        max_attempts=3,
        backoff_seconds=[1, 2, 4],
        retriable_exceptions=(requests.RequestException,),
        retriable_status_codes=[500, 502, 503, 504, 529],
    )
    def consultar_cpf_cnpj(self, documento: str) -> dict[str, Any]:
        """
        Consulta CPF ou CNPJ na Receita Federal via Infosimples.

        Args:
            documento: CPF (11 dígitos) ou CNPJ (14 dígitos), com ou sem máscara.

        Returns:
            Dict normalizado:
            {
                "status": "ATIVO" | "SUSPENSO" | "CANCELADO" | "INEXISTENTE",
                "nome": str | None,
            }

            Cabe à view decidir o que fazer com status != ATIVO (no fluxo
            atual, levanta DocumentoInativoError).

        Levanta:
            InfosimplesError: em caso de falha técnica esgotada (rede, 5xx
                após retries).
        """
        documento_normalizado = normalizar_cpf_cnpj(documento)
        ultimos_4 = self._ultimos_4(documento_normalizado)

        # Modo mock: retorna ATIVO sem chamar a API.
        if self.mock_mode:
            logger.info(
                "Infosimples mock retornando ATIVO",
                extra={
                    "event": "infosimples_mock_response",
                    "documento_ultimos_4": ultimos_4,
                },
            )
            return {"status": STATUS_ATIVO, "nome": "MOCK PESSOA"}

        endpoint = self._endpoint(documento_normalizado)
        params = {
            "token": self.token,
            "cpf" if not self._is_cnpj(documento_normalizado) else "cnpj":
                documento_normalizado,
            "timeout": REQUEST_TIMEOUT,
        }

        start_time = time.time()
        try:
            response = requests.post(
                endpoint, data=params, timeout=REQUEST_TIMEOUT
            )
            duration_ms = (time.time() - start_time) * 1000
            self._log(
                endpoint=endpoint,
                status=response.status_code,
                duration_ms=duration_ms,
                ultimos_4=ultimos_4,
            )
            response.raise_for_status()
            payload = response.json()
        except requests.HTTPError:
            raise  # 5xx retentado pelo decorator; 4xx propagado
        except (requests.ConnectionError, requests.Timeout):
            raise  # Retentado pelo decorator
        except requests.RequestException as exc:
            duration_ms = (time.time() - start_time) * 1000
            self._log(
                endpoint=endpoint,
                status=None,
                duration_ms=duration_ms,
                ultimos_4=ultimos_4,
                error=str(exc),
            )
            raise InfosimplesError(
                message=f"Falha ao consultar Infosimples: {exc}"
            ) from exc

        status_normalizado = self._parse_status(payload)
        nome = self._parse_nome(payload)

        if status_normalizado != STATUS_ATIVO:
            logger.warning(
                "Documento inativo retornado pela Infosimples",
                extra={
                    "event": "infosimples_documento_inativo",
                    "status": status_normalizado,
                    "documento_ultimos_4": ultimos_4,
                },
            )

        return {"status": status_normalizado, "nome": nome}
