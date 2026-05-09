"""
Cliente para o Cloudflare Turnstile — verificação anti-robô (CAPTCHA invisível).

Usado pelo fluxo freemium pós-renegociação 2026-05-08 como primeira camada
de defesa contra bots. Antes de qualquer chamada externa (Infosimples) ou
escrita no banco, a view valida o token Turnstile que o frontend coletou.

Endpoint Cloudflare: POST `https://challenges.cloudflare.com/turnstile/v0/siteverify`
- Form-encoded: `secret`, `response`, `remoteip` (opcional).
- Resposta JSON: `{"success": bool, "error-codes": [...], ...}`.

Mock mode: se `TURNSTILE_SECRET_KEY` estiver vazio (default em dev/test), o
cliente aceita qualquer token não-vazio. Em produção (não-DEBUG e não-test),
levanta `ImproperlyConfigured` — mesmo padrão do `infosimples_client.py`
(P-1 do v1).

Logging estruturado, sem PII.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import requests
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from clama.core.retry import get_current_attempt, with_retry

logger = logging.getLogger("clama.freemium.turnstile")

DEFAULT_VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
REQUEST_TIMEOUT = 10  # segundos


def _is_testing() -> bool:
    """
    Detecta se estamos em contexto de teste.

    P-V3 wave 2: confia exclusivamente em `settings.TESTING` (True em
    `config/settings/test.py`, False default em `base.py`). Removida a
    heurística antiga "test in sys.argv | pytest in sys.modules" — ativava
    falso-positivo de mock_mode em produção quando o processo principal
    incluía argumentos como `--test-connection`, k8s probes, ou
    manifests `test.yaml`. Settings.TESTING é a única fonte da verdade.
    """
    return bool(getattr(settings, "TESTING", False))


class TurnstileClient:
    """
    Wrapper sobre o endpoint de verificação do Cloudflare Turnstile.

    Em modo mock (token vazio em dev/test), aceita qualquer token não-vazio
    para facilitar a suíte. Em produção exige `TURNSTILE_SECRET_KEY` no env
    — falha cedo (P-1) caso contrário.
    """

    # Tokens de sandbox da Cloudflare (sempre passam quando usados com a
    # secret key de teste). Mantidos por documentação, mas o mock_mode
    # aceita qualquer token não-vazio.
    SANDBOX_TOKENS = frozenset(
        {
            "XXXX.DUMMY.TOKEN.XXXX",
            "1x0000000000000000000000000000000AA",
        }
    )

    def __init__(self) -> None:
        self.secret = getattr(settings, "TURNSTILE_SECRET_KEY", "") or ""
        self.verify_url = getattr(
            settings, "TURNSTILE_VERIFY_URL", DEFAULT_VERIFY_URL
        )
        self.mock_mode = self._detect_mock_mode()

    def _detect_mock_mode(self) -> bool:
        """
        Retorna True se devemos rodar em modo mock (sem chamar a Cloudflare).

        - secret vazio + DEBUG → mock mode (dev local).
        - secret vazio + testing → mock mode (suíte automatizada).
        - secret vazio + prod → ImproperlyConfigured (P-1 anti-bypass).
        - secret presente → modo real.
        """
        if not self.secret:
            debug = bool(getattr(settings, "DEBUG", False))
            if not debug and not _is_testing():
                raise ImproperlyConfigured(
                    "TURNSTILE_SECRET_KEY obrigatório em produção — "
                    "mock_mode silencioso desabilitado fora de DEBUG/testes."
                )
            logger.info(
                "TurnstileClient em modo mock",
                extra={"event": "turnstile_mock_mode"},
            )
            return True
        return False

    def _log(
        self,
        status: int | None,
        duration_ms: float,
        success: bool | None,
        error: str | None = None,
    ) -> None:
        log_data: dict[str, Any] = {
            "event": "turnstile_request",
            "status": status,
            "attempt": get_current_attempt(),
            "duration_ms": round(duration_ms, 2),
            "success": success,
        }
        if error:
            log_data["error"] = error
        if error or (status and status >= 400) or success is False:
            logger.warning("Turnstile request failed", extra=log_data)
        else:
            logger.info("Turnstile request completed", extra=log_data)

    @with_retry(
        max_attempts=3,
        backoff_seconds=[1, 2, 4],
        retriable_exceptions=(requests.RequestException,),
        retriable_status_codes=[500, 502, 503, 504],
    )
    def validate(self, token: str, ip: str | None = None) -> bool:
        """
        Valida um token Turnstile.

        Args:
            token: o `cf-turnstile-response` recebido do widget no frontend.
            ip: IP de origem do usuário (opcional, melhora detecção de bots).

        Returns:
            True se o token é válido. False se foi rejeitado pela Cloudflare
            (campo `success=False`).

        Em mock mode aceita qualquer token não-vazio; rejeita string vazia.

        Levanta `requests.RequestException` em falha de rede esgotada
        (após retries) — view captura e converte em pastoral 503.
        """
        if self.mock_mode:
            ok = bool(token)
            logger.info(
                "Turnstile mock mode validate",
                extra={
                    "event": "turnstile_mock_validate",
                    "success": ok,
                },
            )
            return ok

        payload = {
            "secret": self.secret,
            "response": token,
        }
        if ip:
            payload["remoteip"] = ip

        start_time = time.time()
        response = requests.post(
            self.verify_url,
            data=payload,
            timeout=REQUEST_TIMEOUT,
        )
        duration_ms = (time.time() - start_time) * 1000

        # 5xx é retentado pelo decorator; 4xx propaga para a view tratar.
        response.raise_for_status()

        body = response.json()
        success = bool(body.get("success", False))
        self._log(
            status=response.status_code,
            duration_ms=duration_ms,
            success=success,
        )
        return success
