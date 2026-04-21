"""
Cliente wrapper para a API do Asaas.
"""
import logging
import time
from datetime import date
from decimal import Decimal

import requests
from django.conf import settings

from clama.core.retry import get_current_attempt, with_retry
from clama.payments.exceptions import AsaasIntegrationError

logger = logging.getLogger("clama.payments.asaas_client")

REQUEST_TIMEOUT = 10  # segundos


class AsaasClient:
    """
    Cliente para integração com a API do Asaas.

    Implementa retry automático para erros de rede e HTTP 5xx.
    Todos os métodos logam eventos estruturados sem PII.
    """

    def __init__(self):
        """
        Inicializa o cliente com credenciais do settings.
        """
        self.api_key = settings.ASAAS_API_KEY
        self.base_url = settings.ASAAS_BASE_URL
        self.session = requests.Session()
        self.session.headers.update(
            {
                "access_token": self.api_key,
                "Content-Type": "application/json",
            }
        )

    def _log_request(
        self,
        method: str,
        endpoint: str,
        status: int | None,
        duration_ms: float,
        error: str | None = None,
        response_body=None,
    ) -> None:
        """Loga requisição estruturada (sem PII)."""
        log_data = {
            "event": "asaas_request",
            "method": method,
            "endpoint": endpoint,
            "status": status,
            "attempt": get_current_attempt(),
            "duration_ms": round(duration_ms, 2),
        }
        if error:
            log_data["error"] = error
        if response_body is not None:
            log_data["response_body"] = response_body

        if error or (status and status >= 400):
            logger.warning("Asaas request failed", extra=log_data)
        else:
            logger.info("Asaas request completed", extra=log_data)

    @staticmethod
    def _extract_response_body(response):
        """
        Extrai o corpo de uma resposta da Asaas para logging e exceções.

        Returns:
            dict se o body for JSON válido, string truncada (500 chars) caso contrário,
            ou None se a response não existir.
        """
        if response is None:
            return None
        try:
            return response.json()
        except (ValueError, requests.exceptions.JSONDecodeError):
            return response.text[:500] if response.text else None

    @with_retry(max_attempts=3, backoff_seconds=[1, 2, 4])
    def criar_cliente(
        self,
        nome: str,
        email: str,
        cpf_cnpj: str | None = None,
    ) -> dict:
        """
        Cria um cliente (customer) no Asaas.

        Args:
            nome: Nome completo do cliente
            email: Email do cliente
            cpf_cnpj: CPF ou CNPJ (opcional)

        Returns:
            Dict com dados do cliente criado, incluindo 'id'

        Raises:
            AsaasIntegrationError: Se a operação falhar após retries
        """
        endpoint = "/customers"
        url = f"{self.base_url}{endpoint}"

        payload = {
            "name": nome,
            "email": email,
        }
        if cpf_cnpj:
            payload["cpfCnpj"] = cpf_cnpj

        start_time = time.time()
        try:
            response = self.session.post(url, json=payload, timeout=REQUEST_TIMEOUT)
            duration_ms = (time.time() - start_time) * 1000

            self._log_request(
                method="POST",
                endpoint=endpoint,
                status=response.status_code,
                duration_ms=duration_ms,
            )

            response.raise_for_status()
            return response.json()

        except requests.HTTPError as e:
            duration_ms = (time.time() - start_time) * 1000
            upstream_status = e.response.status_code if e.response is not None else None
            upstream_body = self._extract_response_body(e.response)
            self._log_request(
                method="POST",
                endpoint=endpoint,
                status=upstream_status,
                duration_ms=duration_ms,
                error=str(e),
                response_body=upstream_body,
            )
            if upstream_status is not None and upstream_status >= 500:
                raise  # Será retentado pelo decorator
            raise AsaasIntegrationError(
                message=f"Erro ao criar cliente no Asaas (HTTP {upstream_status}): {upstream_body}",
                upstream_status=upstream_status,
                upstream_body=upstream_body,
            ) from e

        except (requests.ConnectionError, requests.Timeout) as e:
            duration_ms = (time.time() - start_time) * 1000
            self._log_request(
                method="POST",
                endpoint=endpoint,
                status=None,
                duration_ms=duration_ms,
                error=str(e),
            )
            raise  # Será retentado pelo decorator

    @with_retry(max_attempts=3, backoff_seconds=[1, 2, 4])
    def criar_cobranca(
        self,
        customer_id: str,
        valor_centavos: int,
        descricao: str,
        pedido_id: str,
        billing_types: list[str] | None = None,
    ) -> dict:
        """
        Cria uma cobrança (payment) no Asaas.

        Args:
            customer_id: ID do cliente no Asaas
            valor_centavos: Valor da cobrança em centavos
            descricao: Descrição da cobrança
            pedido_id: ID do pedido (para callback URL)
            billing_types: Tipos de pagamento aceitos (default: UNDEFINED)

        Returns:
            Dict com dados da cobrança criada, incluindo 'id', 'invoiceUrl', 'status'

        Raises:
            AsaasIntegrationError: Se a operação falhar após retries
        """
        endpoint = "/payments"
        url = f"{self.base_url}{endpoint}"

        # Converte centavos para reais (decimal)
        valor_reais = Decimal(valor_centavos) / Decimal(100)

        # Billing type: UNDEFINED permite todos os métodos
        billing_type = "UNDEFINED"
        if billing_types and len(billing_types) == 1:
            billing_type = billing_types[0]

        payload = {
            "customer": customer_id,
            "billingType": billing_type,
            "value": float(valor_reais),
            "dueDate": date.today().isoformat(),
            "description": descricao,
            "externalReference": pedido_id,  # Para identificar o pedido no webhook
        }

        # Callback só funciona com domínio cadastrado no Asaas
        # TODO: Configurar domínio em Minha Conta > Informações no Asaas
        # frontend_url = getattr(settings, "FRONTEND_URL", "")
        # if frontend_url and not settings.DEBUG:
        #     payload["callback"] = {
        #         "successUrl": f"{frontend_url}/confirmacao?pedido_id={pedido_id}",
        #         "autoRedirect": True,
        #     }

        start_time = time.time()
        try:
            response = self.session.post(url, json=payload, timeout=REQUEST_TIMEOUT)
            duration_ms = (time.time() - start_time) * 1000

            self._log_request(
                method="POST",
                endpoint=endpoint,
                status=response.status_code,
                duration_ms=duration_ms,
            )

            response.raise_for_status()
            return response.json()

        except requests.HTTPError as e:
            duration_ms = (time.time() - start_time) * 1000
            upstream_status = e.response.status_code if e.response is not None else None
            upstream_body = self._extract_response_body(e.response)
            self._log_request(
                method="POST",
                endpoint=endpoint,
                status=upstream_status,
                duration_ms=duration_ms,
                error=str(e),
                response_body=upstream_body,
            )
            if upstream_status is not None and upstream_status >= 500:
                raise  # Será retentado pelo decorator
            raise AsaasIntegrationError(
                message=f"Erro ao criar cobrança no Asaas (HTTP {upstream_status}): {upstream_body}",
                upstream_status=upstream_status,
                upstream_body=upstream_body,
            ) from e

        except (requests.ConnectionError, requests.Timeout) as e:
            duration_ms = (time.time() - start_time) * 1000
            self._log_request(
                method="POST",
                endpoint=endpoint,
                status=None,
                duration_ms=duration_ms,
                error=str(e),
            )
            raise  # Será retentado pelo decorator
