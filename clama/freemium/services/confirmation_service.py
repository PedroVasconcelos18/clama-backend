"""
Service do fluxo de double opt-in por e-mail (renegociação 2026-05-08).

Substitui o `otp_service.py` no fluxo principal: em vez de OTP via SMS/WhatsApp,
o usuário recebe um e-mail com um link contendo um token opaco de confirmação.

API pública:
- `gerar_token(pedido, ip_origem, device_hash) -> str`: cria
  `FreemiumConfirmationToken` para o pedido. Atomic. Retorna a string do token.
- `validar(token_str) -> Pedido`: lê e valida (não-expirado, não-usado), com
  `select_for_update`. NÃO marca como usado — chamador deve invocar
  `marcar_usado` ao final da saga (P-V1 wave 2). Retorna o Pedido associado.
- `marcar_usado(token_str) -> None`: marca o token como consumido (`used_at`).
  Idempotente. Chamado APÓS o sucesso da saga, dentro da MESMA `atomic()`
  envolvendo a saga inteira — assim, qualquer falha rolla back o `used_at`
  e o token volta a usável (cumpre a regra do frozen "Falha em qualquer
  ponto: rollback completo, token volta a usável").
- `validar_e_consumir(token_str) -> Pedido`: alias DEPRECATED mantido por
  compatibilidade com testes legados; faz validar + marcar_usado em UMA
  transação (não compõe com saga externa). Novos chamadores devem usar
  `validar` e `marcar_usado` separadamente envolvidos pela própria atomic.

Erros possíveis (ambos `PastoralAPIException` 400):
- `ConfirmationTokenInvalidoError`: token não existe ou já foi usado.
- `ConfirmationTokenExpiradoError`: TTL passou (24h default).

Logging estruturado, sem PII (logamos apenas prefixo do token).
"""

from __future__ import annotations

import logging
import secrets

from django.db import transaction
from django.utils import timezone

from clama.freemium.exceptions import (
    ConfirmationTokenExpiradoError,
    ConfirmationTokenInvalidoError,
)
from clama.freemium.models import FreemiumConfirmationToken
from clama.orders.models import Pedido

logger = logging.getLogger("clama.freemium.confirmation")

# Comprimento máximo do `token` no model (CharField max_length=64).
TOKEN_MAX_LEN = 64


def _gerar_string_opaca() -> str:
    """
    Gera string opaca para uso como token.

    `secrets.token_urlsafe(48)` produz exatamente 64 chars URL-safe (cada
    3 bytes vira 4 chars base64; 48/3*4 = 64). 48 bytes = 384 bits de
    entropia — bem além dos 256 bits exigidos pela spec.

    P-V16 wave 2: removido `[:TOKEN_MAX_LEN]` no final — `token_urlsafe(48)`
    sempre retorna 64 chars exatos (RFC 4648 sem padding); o slice era
    no-op e induzia leitor a achar que o tamanho podia variar. Mantida a
    constante `TOKEN_MAX_LEN` apenas como referência do schema.
    """
    return secrets.token_urlsafe(48)


def gerar_token(
    pedido: Pedido,
    ip_origem: str | None,
    device_hash: str,
) -> str:
    """
    Cria `FreemiumConfirmationToken` para o pedido informado, em transação
    atômica, e retorna a string do token.

    Args:
        pedido: instância de `orders.Pedido` em status
            `AGUARDANDO_CONFIRMACAO_EMAIL`.
        ip_origem: IP do request da submissão (pode ser `None` se não
            disponível).
        device_hash: hash do device fingerprint capturado no frontend.
            Pode ser string vazia.

    Returns:
        Token string (max 64 chars) — usar no link do e-mail de confirmação.
    """
    token_str = _gerar_string_opaca()
    with transaction.atomic():
        FreemiumConfirmationToken.objects.create(
            token=token_str,
            pedido=pedido,
            ip_origem=ip_origem,
            device_hash=device_hash or "",
        )
    logger.info(
        "Token de confirmação freemium gerado",
        extra={
            "event": "freemium_confirmation_token_gerado",
            "pedido_id": str(pedido.id),
            "token_prefixo": token_str[:8],
        },
    )
    return token_str


def validar(token_str: str) -> Pedido:
    """
    Valida o token (existe, não-expirado, não-usado) e retorna o Pedido
    associado SEM marcar como usado.

    P-V1 wave 2: separado de `validar_e_consumir`. A view envolve este
    método + a saga + `marcar_usado` em UMA `transaction.atomic()` única.
    Assim, qualquer falha (saga, blacklist hit, integrity) rolla back o
    `used_at` e o token volta a usável (cumpre frozen linha 30:
    "Falha em qualquer ponto: rollback completo, token volta a usável").

    Atomic: usa `select_for_update` para serializar cliques simultâneos no
    mesmo link. O segundo request bloqueia até o primeiro commitar e então
    enxerga `used_at` setado, caindo em `ConfirmationTokenInvalidoError`.

    Args:
        token_str: valor exato do token (sem prefixo de URL).

    Returns:
        Pedido associado ao token.

    Raises:
        ConfirmationTokenInvalidoError: token não existe ou já foi consumido.
        ConfirmationTokenExpiradoError: TTL passou.
    """
    if not token_str:
        raise ConfirmationTokenInvalidoError()

    # `select_for_update` defende corrida entre dois cliques no mesmo
    # link. Garante que apenas um request consegue avançar até o
    # `marcar_usado` final.
    try:
        token = (
            FreemiumConfirmationToken.objects
            .select_for_update()
            .select_related("pedido")
            .get(token=token_str)
        )
    except FreemiumConfirmationToken.DoesNotExist as exc:
        logger.info(
            "Tentativa de uso de token inexistente",
            extra={
                "event": "freemium_confirmation_token_inexistente",
                "token_prefixo": (token_str or "")[:8],
            },
        )
        raise ConfirmationTokenInvalidoError() from exc

    if token.used_at is not None:
        logger.info(
            "Tentativa de reuso de token já consumido",
            extra={
                "event": "freemium_confirmation_token_ja_usado",
                "pedido_id": str(token.pedido_id),
                "token_prefixo": token_str[:8],
            },
        )
        raise ConfirmationTokenInvalidoError()

    agora = timezone.now()
    if token.expires_at <= agora:
        logger.info(
            "Tentativa de uso de token expirado",
            extra={
                "event": "freemium_confirmation_token_expirado",
                "pedido_id": str(token.pedido_id),
                "token_prefixo": token_str[:8],
            },
        )
        raise ConfirmationTokenExpiradoError()

    return token.pedido


def marcar_usado(token_str: str) -> None:
    """
    Marca o token como consumido (`used_at = now`).

    P-V1 wave 2: chamado APÓS a saga ter sucesso, dentro da MESMA
    `transaction.atomic()` envolvendo a saga. Se a saga falhar antes,
    `marcar_usado` não é chamado e o `used_at` permanece nulo. Se já estiver
    setado (race), a operação é idempotente (no-op).

    Args:
        token_str: valor exato do token. Vazio é tratado como invalid (raise).

    Raises:
        ConfirmationTokenInvalidoError: token não existe (defesa em
            profundidade — não deveria acontecer se `validar` rodou antes
            no mesmo atomic).
    """
    if not token_str:
        raise ConfirmationTokenInvalidoError()

    try:
        token = FreemiumConfirmationToken.objects.get(token=token_str)
    except FreemiumConfirmationToken.DoesNotExist as exc:
        raise ConfirmationTokenInvalidoError() from exc

    if token.used_at is None:
        token.used_at = timezone.now()
        token.save(update_fields=["used_at", "updated_at"])

    logger.info(
        "Token de confirmação freemium consumido",
        extra={
            "event": "freemium_confirmation_token_consumido",
            "pedido_id": str(token.pedido_id),
            "token_prefixo": token_str[:8],
        },
    )


def validar_e_consumir(token_str: str) -> Pedido:
    """
    DEPRECATED — mantém compat com testes legados. Use `validar` +
    `marcar_usado` separadamente, envolvendo ambos pela `atomic()` da saga.

    Esta função abre seu próprio `transaction.atomic()` e marca `used_at`
    imediatamente — é INCOMPATÍVEL com o saga atomic do P-V1 wave 2 (faria
    o `used_at` commitar antes da saga rodar, então uma falha da saga
    deixaria o token consumido + Pedido stuck).

    Mantida só para a suíte de testes do confirmation service que valida
    os caminhos de erro (token inexistente / expirado / já-usado) sem
    depender da saga completa.
    """
    with transaction.atomic():
        pedido = validar(token_str)
        marcar_usado(token_str)
        return pedido
