"""
Models do app freemium.

A `FreemiumBlacklist` registra os identificadores (CPF/CNPJ, e-mail) que já
consumiram seu pedido gratuito. Armazenamos apenas hashes HMAC-SHA-256 keyed
— não guardamos PII em claro nesta tabela. O lookup acontece
hashing-then-compare.

Pós-renegociação 2026-05-08: o `telefone_hash` foi removido. Sem OTP que
confirmasse posse do número, hash de telefone era falso-positivo (qualquer
um digita um número arbitrário e bloqueia outra pessoa).

`FreemiumConfirmationToken` armazena o token opaco enviado por e-mail no
fluxo double opt-in: TTL 24h, single-use, validado e consumido na rota
`/api/freemium/confirmar/`.
"""

from datetime import timedelta

from django.db import models
from django.utils import timezone

from clama.core.models import TimestampedModel, UUIDPKModel

# TTL default do token de confirmação por e-mail (24h, conforme spec).
CONFIRMATION_TOKEN_TTL = timedelta(hours=24)


class FreemiumBlacklist(UUIDPKModel, TimestampedModel):
    """
    Registro de identificadores que já consumiram o pedido gratuito.

    Cada hash é único individualmente — qualquer um dos dois (CPF ou
    e-mail) bater na blacklist bloqueia novo pedido grátis.
    """

    cpf_hash = models.CharField(
        max_length=64,
        unique=True,
        db_index=True,
        verbose_name="Hash do CPF/CNPJ",
        help_text="SHA-256 do CPF/CNPJ normalizado (somente dígitos).",
    )
    email_hash = models.CharField(
        max_length=64,
        unique=True,
        db_index=True,
        verbose_name="Hash do e-mail",
        help_text="SHA-256 do e-mail normalizado (lowercase + strip).",
    )

    class Meta:
        verbose_name = "Entrada da Blacklist Freemium"
        verbose_name_plural = "Blacklist Freemium"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        # Não expomos o hash inteiro em listagens — apenas prefixo curto.
        return f"FreemiumBlacklist({self.cpf_hash[:8]}…)"


def _default_expiracao() -> "timezone.datetime":
    """Default do `expires_at`: agora + TTL de 24h."""
    return timezone.now() + CONFIRMATION_TOKEN_TTL


class FreemiumConfirmationToken(UUIDPKModel, TimestampedModel):
    """
    Token opaco enviado por e-mail no fluxo double opt-in.

    Persistido na criação do Pedido (status `AGUARDANDO_CONFIRMACAO_EMAIL`).
    No clique do link, a view `/api/freemium/confirmar/` valida e consome
    via `validar_e_consumir`. Single-use (marca `used_at`), TTL 24h.

    `ip_origem` e `device_hash` são copiados do request da submissão para
    instrumentação de fraude.
    """

    token = models.CharField(
        max_length=64,
        unique=True,
        db_index=True,
        verbose_name="Token opaco",
        help_text="secrets.token_urlsafe(48) truncado em 64 chars.",
    )
    pedido = models.ForeignKey(
        "orders.Pedido",
        on_delete=models.CASCADE,
        related_name="confirmation_tokens",
        verbose_name="Pedido",
    )
    expires_at = models.DateTimeField(
        default=_default_expiracao,
        verbose_name="Expira em",
        help_text="Default: criação + 24h.",
    )
    used_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Usado em",
    )
    ip_origem = models.GenericIPAddressField(
        null=True,
        blank=True,
        verbose_name="IP de origem",
    )
    device_hash = models.CharField(
        max_length=128,
        blank=True,
        default="",
        verbose_name="Device fingerprint",
    )

    class Meta:
        verbose_name = "Token de confirmação freemium"
        verbose_name_plural = "Tokens de confirmação freemium"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"FreemiumConfirmationToken({self.token[:8]}…)"
