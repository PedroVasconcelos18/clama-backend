"""
Serializers da API freemium.

Padrão: serializers separados de request e response — não usamos
ModelSerializer porque o pedido freemium tem campos derivados (consent_aceito,
turnstile_token, device_hash) e a resposta nunca expõe dados sensíveis.

Pós-renegociação 2026-05-08: removidos os serializers de OTP. A submissão
do pedido agora carrega `turnstile_token` (CAPTCHA Cloudflare) e
`device_hash` (FingerprintJS) no lugar do par `otp_token`/`otp_codigo`.
A confirmação por e-mail (double opt-in) acontece via endpoint separado.
"""

import re

from rest_framework import serializers

from clama.core.validators_documento import validar_documento
from clama.orders.models import Sexo

# E.164: '+' seguido de 8 a 15 dígitos. Validação ampla — o serviço Z-API
# aplica regra mais estrita (Brasil) na hora do envio.
E164_REGEX = re.compile(r"^\+[1-9]\d{7,14}$")


def _validate_telefone_e164(value: str) -> str:
    """Valida E.164 (`+` + 8-15 dígitos). Retorna o valor já normalizado."""
    if not value:
        raise serializers.ValidationError(
            "Confira seu telefone com DDD — vamos enviar a oração por aqui."
        )
    valor = value.strip()
    if not E164_REGEX.match(valor):
        raise serializers.ValidationError(
            "Telefone deve estar no formato internacional (ex.: +5511999999999)."
        )
    return valor


def _validate_cpf_cnpj(value: str) -> str:
    """Valida CPF/CNPJ pelo dígito verificador. Retorna apenas dígitos."""
    if not value:
        raise serializers.ValidationError("Por favor, digite seu CPF ou CNPJ.")
    try:
        return validar_documento(value)
    except ValueError as exc:
        raise serializers.ValidationError(str(exc)) from exc


class PedidoFreemiumCreateRequestSerializer(serializers.Serializer):
    """
    Payload do POST /api/freemium/pedidos/ (pós-renegociação 2026-05-08).

    Substitui `otp_token`/`otp_codigo` por `turnstile_token` (CAPTCHA
    invisível) + `device_hash` (FingerprintJS). Telefone permanece
    obrigatório (decisão Pedro: gravado no Pedido pra fluxo WhatsApp futuro).
    """

    nome = serializers.CharField(max_length=120, min_length=2)
    email = serializers.EmailField()
    telefone = serializers.CharField(max_length=20)
    cpf_cnpj = serializers.CharField(max_length=20)
    idade = serializers.IntegerField(
        required=False, allow_null=True, min_value=1, max_value=120
    )
    sexo = serializers.ChoiceField(choices=Sexo.choices, allow_blank=True, required=False)
    pedido_oracao = serializers.CharField(
        max_length=2000, allow_blank=True, required=False
    )
    consent_aceito = serializers.BooleanField()
    turnstile_token = serializers.CharField(
        min_length=1,
        max_length=2048,
        help_text=(
            "Token do Cloudflare Turnstile capturado pelo widget no front."
        ),
    )
    device_hash = serializers.CharField(
        max_length=128,
        required=False,
        allow_blank=True,
        default="",
        help_text=(
            "Hash do device fingerprint coletado pelo FingerprintJS no front. "
            "Opcional (P-V15 wave 2) — frozen MVP é instrumentação only, "
            "então uma falha no FingerprintJS (Brave shields, ad-block) não "
            "deve bloquear o usuário. Persistido como string vazia se ausente."
        ),
    )

    def validate_cpf_cnpj(self, value: str) -> str:
        return _validate_cpf_cnpj(value)

    def validate_telefone(self, value: str) -> str:
        return _validate_telefone_e164(value)

    def validate_consent_aceito(self, value: bool) -> bool:
        if not value:
            raise serializers.ValidationError(
                "Para enviar seu pedido, é preciso concordar com a política de privacidade."
            )
        return value


class PedidoFreemiumCreateResponseSerializer(serializers.Serializer):
    """
    Resposta 201 do POST /api/freemium/pedidos/.

    Pós-renegociação: o User ainda NÃO existe na submissão (só após
    confirmação por e-mail), então não devolvemos `login_email` aqui.
    """

    pedido_id = serializers.UUIDField()
    status = serializers.CharField()


class FreemiumConfirmarResponseSerializer(serializers.Serializer):
    """
    Resposta JSON do GET/POST /api/freemium/confirmar/ quando Accept JSON.

    No happy path o status devolvido é sempre `GERANDO_ORACAO` — a saga
    foi executada (User criado, blacklist gravada, task disparada).
    """

    pedido_id = serializers.UUIDField()
    status = serializers.CharField()
