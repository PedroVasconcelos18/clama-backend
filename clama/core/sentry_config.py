"""
Configuração do Sentry com redaction de PII.

Este módulo configura o Sentry com:
- Sampling rates otimizados para produção
- Redação automática de campos sensíveis (LGPD)
- Fingerprinting para agrupar erros similares
"""

import re
from typing import Any

# Campos que contêm PII e devem ser redatados
PII_FIELDS = {
    "email",
    "telefone",
    "nome",
    "pedido_oracao",
    "oracao_gerada",
    "phone",
    "name",
    "password",
    "senha",
    "token",
    "refresh",
    "access",
}

# Padrão para detectar emails em strings
EMAIL_PATTERN = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")

# Padrão para detectar telefones brasileiros
PHONE_PATTERN = re.compile(r"\(?\d{2}\)?\s*\d{4,5}[-\s]?\d{4}")


def _redact_value(key: str, value: Any) -> Any:
    """Redact um valor se a chave indicar PII."""
    if not isinstance(value, str):
        return value

    key_lower = key.lower()

    # Redact campos conhecidos como PII
    if any(pii_field in key_lower for pii_field in PII_FIELDS):
        return "[REDACTED]"

    # Redact emails detectados em strings
    value = EMAIL_PATTERN.sub("[EMAIL_REDACTED]", value)

    # Redact telefones detectados
    value = PHONE_PATTERN.sub("[PHONE_REDACTED]", value)

    return value


def _redact_dict(data: dict) -> dict:
    """Redact recursivamente um dicionário."""
    if not isinstance(data, dict):
        return data

    redacted = {}
    for key, value in data.items():
        if isinstance(value, dict):
            redacted[key] = _redact_dict(value)
        elif isinstance(value, list):
            redacted[key] = [
                _redact_dict(item) if isinstance(item, dict) else _redact_value(key, item)
                for item in value
            ]
        else:
            redacted[key] = _redact_value(key, value)

    return redacted


def before_send(event: dict, hint: dict) -> dict | None:
    """
    Callback executado antes de enviar evento ao Sentry.

    Redact campos PII em:
    - request data
    - extra data
    - tags
    - breadcrumbs
    """
    # Redact request data
    if "request" in event:
        if "data" in event["request"]:
            event["request"]["data"] = _redact_dict(event["request"]["data"])
        if "headers" in event["request"]:
            event["request"]["headers"] = _redact_dict(event["request"]["headers"])

    # Redact extra/contexts
    if "extra" in event:
        event["extra"] = _redact_dict(event["extra"])

    if "contexts" in event:
        event["contexts"] = _redact_dict(event["contexts"])

    # Redact tags
    if "tags" in event:
        event["tags"] = _redact_dict(event["tags"])

    # Redact breadcrumbs
    if "breadcrumbs" in event and "values" in event["breadcrumbs"]:
        for breadcrumb in event["breadcrumbs"]["values"]:
            if "data" in breadcrumb:
                breadcrumb["data"] = _redact_dict(breadcrumb["data"])
            if "message" in breadcrumb:
                breadcrumb["message"] = _redact_value("message", breadcrumb["message"])

    # Redact exception values (mensagens de erro podem conter PII)
    if "exception" in event and "values" in event["exception"]:
        for exc in event["exception"]["values"]:
            if "value" in exc:
                exc["value"] = _redact_value("exception_value", exc["value"])

    return event


def init_sentry(dsn: str, environment: str) -> None:
    """
    Inicializa o Sentry com configurações otimizadas para produção.

    Args:
        dsn: Sentry DSN
        environment: Ambiente (local, staging, production)
    """
    import sentry_sdk
    from sentry_sdk.integrations.celery import CeleryIntegration
    from sentry_sdk.integrations.django import DjangoIntegration
    from sentry_sdk.integrations.logging import LoggingIntegration

    # Configurações por ambiente
    if environment == "production":
        traces_sample_rate = 0.1  # 10% das requests
        profiles_sample_rate = 0.0  # Desligado em prod (custo)
    else:
        traces_sample_rate = 1.0  # 100% em staging/local
        profiles_sample_rate = 0.0

    sentry_sdk.init(
        dsn=dsn,
        environment=environment,
        integrations=[
            DjangoIntegration(),
            CeleryIntegration(),
            LoggingIntegration(
                level=None,  # Não captura logs automaticamente
                event_level=None,
            ),
        ],
        traces_sample_rate=traces_sample_rate,
        profiles_sample_rate=profiles_sample_rate,
        send_default_pii=False,  # Nunca enviar PII automaticamente
        before_send=before_send,  # Redação adicional de PII
        # Ignora erros comuns que não precisam de atenção
        ignore_errors=[
            "django.security.DisallowedHost",
        ],
    )
