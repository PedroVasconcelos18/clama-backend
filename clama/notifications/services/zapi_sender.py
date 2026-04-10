"""
Implementação do WhatsAppSender usando Z-API.
"""

import logging
import re
import time

import requests
from django.conf import settings

from clama.core.retry import with_retry
from clama.notifications.exceptions import WhatsAppIntegrationError
from clama.notifications.utils import format_telefone_zapi

logger = logging.getLogger("clama.notifications.whatsapp")

REQUEST_TIMEOUT = 15  # segundos


class ZapiSender:
    """
    Envia mensagens WhatsApp via Z-API.

    Implementa o protocol WhatsAppSender.

    Configuração via env vars:
    - ZAPI_INSTANCE_ID
    - ZAPI_TOKEN
    - ZAPI_BASE_URL (default: https://api.z-api.io)
    """

    def __init__(self):
        """Inicializa com credenciais do settings."""
        self.instance_id = settings.ZAPI_INSTANCE_ID
        self.token = settings.ZAPI_TOKEN
        self.base_url = getattr(settings, "ZAPI_BASE_URL", "https://api.z-api.io")

    def _validate_telefone(self, telefone: str) -> None:
        """Valida que telefone está no formato E.164 brasileiro."""
        if not re.fullmatch(r"\+55\d{10,11}", telefone):
            raise ValueError(
                f"Telefone deve estar no formato E.164 brasileiro (+55XXXXXXXXXXX): {telefone}"
            )

    def _log_request(
        self,
        status: int | None,
        attempt: int,
        duration_ms: float,
        error: str | None = None,
    ) -> None:
        """Loga requisição estruturada (sem PII)."""
        log_data = {
            "event": "whatsapp_send",
            "provider": "zapi",
            "status": status,
            "attempt": attempt,
            "duration_ms": round(duration_ms, 2),
        }
        if error:
            log_data["error"] = error

        if error or (status and status >= 400):
            logger.warning("Z-API request failed", extra=log_data)
        else:
            logger.info("Z-API request completed", extra=log_data)

    @with_retry(max_attempts=3, backoff_seconds=[1, 2, 4])
    def send(self, telefone: str, mensagem: str) -> dict:
        """
        Envia mensagem de texto via WhatsApp.

        Args:
            telefone: Número no formato E.164 (+5511999999999)
            mensagem: Texto da mensagem

        Returns:
            dict com provider_message_id: str

        Raises:
            ValueError: Se telefone não estiver no formato E.164
            WhatsAppIntegrationError: Se envio falhar após retries
        """
        # Valida formato antes de chamar API
        self._validate_telefone(telefone)

        # Monta URL
        url = f"{self.base_url}/instances/{self.instance_id}/token/{self.token}/send-text"

        # Payload - Z-API espera número sem o +
        payload = {
            "phone": format_telefone_zapi(telefone),
            "message": mensagem,
        }

        start_time = time.time()
        attempt = 1

        try:
            response = requests.post(url, json=payload, timeout=REQUEST_TIMEOUT)
            duration_ms = (time.time() - start_time) * 1000

            self._log_request(
                status=response.status_code,
                attempt=attempt,
                duration_ms=duration_ms,
            )

            response.raise_for_status()

            # Parse response
            data = response.json()
            message_id = data.get("messageId") or data.get("id") or ""

            return {"provider_message_id": message_id}

        except requests.HTTPError as e:
            duration_ms = (time.time() - start_time) * 1000
            self._log_request(
                status=e.response.status_code if e.response else None,
                attempt=attempt,
                duration_ms=duration_ms,
                error=str(e),
            )

            # 5xx são retentados pelo decorator
            if e.response is not None and e.response.status_code >= 500:
                raise

            # 4xx indicam erro de configuração - não retenta
            raise WhatsAppIntegrationError(
                message=f"Erro ao enviar WhatsApp: {e}"
            ) from e

        except (requests.ConnectionError, requests.Timeout) as e:
            duration_ms = (time.time() - start_time) * 1000
            self._log_request(
                status=None,
                attempt=attempt,
                duration_ms=duration_ms,
                error=str(e),
            )
            raise  # Retentado pelo decorator

        except requests.RequestException as e:
            raise WhatsAppIntegrationError(
                message=f"Erro ao enviar WhatsApp: {e}"
            ) from e
