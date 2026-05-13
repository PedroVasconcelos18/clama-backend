"""
Models do app freemium.

A `FreemiumBlacklist` registra os identificadores (CPF/CNPJ, e-mail,
telefone) que já consumiram seu pedido gratuito. Armazenamos apenas hashes
HMAC-SHA-256 keyed — não guardamos PII em claro nesta tabela. O lookup
acontece hashing-then-compare.

Histórico:
- 2026-05-08 (renegociação): `telefone_hash` removido (sem OTP, falso-positivo).
- 2026-05-10 (spec lp-user-existence-gate): `telefone_hash` re-adicionado
  como anti-bypass (combinado com user-existence gate, telefone agora cobre
  o caso "user já existe mas tenta com email/CPF diferente"). É nullable
  porque o backfill da 0005 popula a partir do `Pedido.telefone` linkado.

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
    telefone_hash = models.CharField(
        max_length=64,
        db_index=True,
        null=True,
        blank=True,
        verbose_name="Hash do telefone",
        help_text=(
            "HMAC-SHA-256 do telefone (somente dígitos). Re-adicionado em "
            "2026-05-10 — nullable pra suportar entries legadas sem telefone."
        ),
    )
    device_hash = models.CharField(
        max_length=128,
        db_index=True,
        null=True,
        blank=True,
        verbose_name="Device fingerprint",
        help_text=(
            "visitorId do FingerprintJS coletado no submit. Bloqueia submits "
            "subsequentes da mesma máquina+browser mesmo com CPF/email/"
            "telefone diferentes (anti-bypass de aba anônima / email "
            "temporário). Nullable: pode vir vazio se FingerprintJS falhar "
            "(Brave shields, adblockers) — nesse caso não bloqueia."
        ),
    )
    ip_hash = models.CharField(
        max_length=64,
        db_index=True,
        null=True,
        blank=True,
        verbose_name="Hash do IP de origem",
        help_text=(
            "HMAC-SHA-256 do consent_ip do Pedido. Bloqueia submits da mesma "
            "rede dentro da janela de IP_BLACKLIST_WINDOW (default 24h). "
            "Camada extra anti-bypass quando device_hash é instável (Brave, "
            "Safari, modo private). Trade-off: bloqueia famílias atrás do "
            "mesmo IP — admin pode desbloquear manualmente."
        ),
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
