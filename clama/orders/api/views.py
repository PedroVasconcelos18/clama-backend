"""
Views da API de pedidos.
"""

import logging

import requests
import sentry_sdk
from django.core.exceptions import ValidationError
from django.core.validators import validate_ipv46_address
from django.db import transaction
from drf_spectacular.utils import OpenApiExample, OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.generics import CreateAPIView, RetrieveAPIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle

from clama.core.exceptions import PastoralAPIException
from clama.core.permissions import IsCustomerPasswordCurrent
from clama.core.throttles import EmailScopedThrottle
from clama.freemium.exceptions import EmailDescartavelError, TurnstileInvalidoError
from clama.freemium.services.email_blacklist import is_disposable
from clama.freemium.services.turnstile_client import TurnstileClient
from clama.orders.api.serializers import (
    DoacaoAnonimaCreateSerializer,
    PedidoCreateSerializer,
    PedidoGratuitoCreateSerializer,
    PedidoResponseSerializer,
    PedidoStatusSerializer,
)
from clama.orders.models import Pedido

logger = logging.getLogger("clama.orders.views")


def _ip_request(request) -> str | None:
    """
    Extrai o IP do request (X-Forwarded-For → REMOTE_ADDR), validando o
    formato. Retorna None se ausente/malformado. Espelha o helper do fluxo
    freemium — usado como `remoteip` na verificação Turnstile.
    """
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        ip = forwarded.split(",")[0].strip()
    else:
        ip = request.META.get("REMOTE_ADDR")

    if not ip:
        return None
    try:
        validate_ipv46_address(ip)
    except ValidationError:
        return None
    return ip


class PedidoCreateView(CreateAPIView):
    """
    Cria um novo pedido de oração (fluxo pago, autenticado).

    Spec G2.a backend (entregue via spec lp-user-existence-gate em
    2026-05-10): exige `IsAuthenticated` + `IsCustomerPasswordCurrent`. O
    user precisa ter conta (criada via saga G1 freemium ou G4 futuro) e
    ter trocado a senha temporária. O `Pedido.user` é setado a partir do
    `request.user` no serializer.

    Rate limiting:
    - 10 requests/minuto por IP (ScopedRateThrottle)
    - 5 pedidos/hora por email (EmailScopedThrottle)
    """

    serializer_class = PedidoCreateSerializer
    permission_classes = [IsAuthenticated, IsCustomerPasswordCurrent]
    throttle_classes = [ScopedRateThrottle, EmailScopedThrottle]
    throttle_scope = "pedidos_create"

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        pedido = serializer.save()

        # Usar serializer de resposta sem dados sensíveis
        response_serializer = PedidoResponseSerializer(pedido)
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)

    @extend_schema(
        tags=["Pedidos"],
        summary="Criar pedido de oração",
        description="Cria um novo pedido de oração. Retorna o ID do pedido para prosseguir ao pagamento.",
        request=PedidoCreateSerializer,
        responses={
            201: OpenApiResponse(
                response=PedidoResponseSerializer,
                description="Pedido criado com sucesso",
            ),
            400: OpenApiResponse(
                description="Erro de validação",
            ),
            429: OpenApiResponse(
                description="Rate limit excedido",
            ),
        },
        examples=[
            OpenApiExample(
                "Exemplo de request",
                value={
                    "nome": "Maria Silva",
                    "email": "maria@example.com",
                    "telefone": "(11) 99999-8888",
                    "idade": 35,
                    "sexo": "feminino",
                    "pedido_oracao": "Peço oração pela minha família.",
                    "plano": "550e8400-e29b-41d4-a716-446655440000",
                    "valor_centavos": 2000,
                    "canal_entrega": "email",
                },
                request_only=True,
            ),
            OpenApiExample(
                "Exemplo de resposta",
                value={
                    "id": "660e9500-f39c-52e5-b827-557766551111",
                    "status": "aguardando_pagamento",
                    "valor_reais_str": "R$ 20,00",
                    "canal_entrega": "email",
                    "created_at": "2024-01-15T10:30:00Z",
                },
                response_only=True,
                status_codes=["201"],
            ),
        ],
    )
    def post(self, request, *args, **kwargs):
        return super().post(request, *args, **kwargs)


class PedidoGratuitoCreateView(CreateAPIView):
    """
    Cria um pedido de oração GRATUITO (usuário autenticado, card "Gratuito"
    em Minha Conta).

    Não passa pelo gateway de pagamento: o pedido nasce `eh_gratuito=True` em
    `GERANDO_ORACAO` e a geração da oração é disparada na hora. Sem trava
    freemium (grátis ilimitado nesta tela autenticada, por decisão de
    produto).

    Exige `IsAuthenticated` + `IsCustomerPasswordCurrent` (mesma postura do
    fluxo pago).
    """

    serializer_class = PedidoGratuitoCreateSerializer
    permission_classes = [IsAuthenticated, IsCustomerPasswordCurrent]
    throttle_classes = [ScopedRateThrottle, EmailScopedThrottle]
    throttle_scope = "pedidos_create"

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        pedido = serializer.save()

        # Dispara a geração após o commit (padrão do webhook/freemium).
        from clama.prayer_generation.tasks import gerar_oracao_task

        pedido_id = str(pedido.id)
        transaction.on_commit(lambda: gerar_oracao_task.delay(pedido_id))

        response_serializer = PedidoResponseSerializer(pedido)
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)

    @extend_schema(
        tags=["Pedidos"],
        summary="Criar pedido de oração gratuito",
        description=(
            "Cria um pedido gratuito e dispara a geração da oração, sem "
            "pagamento. Apenas usuário autenticado."
        ),
        request=PedidoGratuitoCreateSerializer,
        responses={
            201: OpenApiResponse(
                response=PedidoResponseSerializer,
                description="Pedido gratuito criado e geração disparada",
            ),
            400: OpenApiResponse(description="Erro de validação"),
            401: OpenApiResponse(description="Não autenticado"),
            429: OpenApiResponse(description="Rate limit excedido"),
        },
    )
    def post(self, request, *args, **kwargs):
        return super().post(request, *args, **kwargs)


class DoacaoAnonimaCreateView(CreateAPIView):
    """
    POST /api/doacoes/ — doação paga SEM conta (LP, doador anônimo).

    Coexiste com o freemium grátis. Pipeline anti-fraude (na ordem, ANTES de
    qualquer escrita), espelhando `PedidoFreemiumCreateView` — porém SEM a
    `FreemiumBlacklist` e SEM o gate de user-existente (doação é repetível e
    um doador com conta pode doar):
      1. Deserializa o payload (valida valor, consent, CPF/CNPJ, turnstile_token).
      2. Valida o CAPTCHA Turnstile (primeiro — mata bots antes de qualquer trabalho).
      3. Checa e-mail descartável.
      4. Cria o Pedido anônimo (`user=None`, AGUARDANDO_PAGAMENTO).

    Retorna 201 com o id do pedido; o front segue para
    `POST /api/pedidos/<id>/checkout/` (Pix, `AllowAny`). O provisionamento /
    vínculo da conta acontece depois, no webhook de pagamento (idempotente).
    """

    serializer_class = DoacaoAnonimaCreateSerializer
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "doacao_ip"

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        turnstile_token = data["turnstile_token"]
        email = data.get("email") or ""
        request_ip = _ip_request(request)

        # 1. CAPTCHA Turnstile primeiro — antes de qualquer escrita. Token é
        # single-use na Cloudflare: valida UMA vez aqui, não revalida no checkout.
        turnstile = TurnstileClient()
        try:
            captcha_ok = turnstile.validate(turnstile_token, ip=request_ip)
        except requests.RequestException as exc:
            sentry_sdk.capture_exception(exc)
            logger.error(
                "Falha permanente ao validar Turnstile (doação)",
                extra={
                    "event": "doacao_turnstile_falha_permanente",
                    "error": str(exc),
                },
            )
            raise TurnstileInvalidoError() from exc

        if not captcha_ok:
            raise TurnstileInvalidoError()

        # 2. Anti e-mail descartável (mesma checagem do freemium).
        if is_disposable(email):
            raise EmailDescartavelError()

        # 3. Cria o Pedido anônimo (user=None).
        pedido = serializer.save()

        response_serializer = PedidoResponseSerializer(pedido)
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)

    @extend_schema(
        tags=["Pedidos"],
        summary="Criar doação paga sem conta",
        description=(
            "Cria um pedido de doação para doador anônimo (sem conta), "
            "validando Turnstile e e-mail descartável antes de qualquer "
            "escrita. Retorna o ID do pedido para prosseguir ao checkout."
        ),
        request=DoacaoAnonimaCreateSerializer,
        responses={
            201: OpenApiResponse(
                response=PedidoResponseSerializer,
                description="Doação criada (aguardando pagamento)",
            ),
            400: OpenApiResponse(
                description="CAPTCHA inválido / e-mail descartável / dados inválidos",
            ),
            429: OpenApiResponse(description="Rate limit por IP excedido"),
        },
    )
    def post(self, request, *args, **kwargs):
        return super().post(request, *args, **kwargs)


class PedidoStatusView(RetrieveAPIView):
    """
    Consulta o status de um pedido de oração.

    UUID atua como token de leitura. Não expõe dados pessoais.
    Rate limit: 60 requests/minuto por IP.
    """

    serializer_class = PedidoStatusSerializer
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "pedidos_status"
    queryset = Pedido.objects.all()
    lookup_field = "id"

    def get_object(self):
        """
        Retorna o pedido ou levanta exceção pastoral se não encontrado.
        """
        try:
            return super().get_object()
        except Exception:
            raise PastoralAPIException(
                code="not_found",
                message="Pedido não encontrado",
                pastoral_message="Não encontramos esse pedido. Pode tentar novamente?",
                status_code=404,
            )

    @extend_schema(
        tags=["Pedidos"],
        summary="Consultar status do pedido",
        description="UUID atua como token de leitura. Não expõe dados pessoais.",
        responses={
            200: OpenApiResponse(
                response=PedidoStatusSerializer,
                description="Status do pedido",
            ),
            404: OpenApiResponse(
                description="Pedido não encontrado",
            ),
            429: OpenApiResponse(
                description="Rate limit excedido",
            ),
        },
        examples=[
            OpenApiExample(
                "Exemplo de resposta",
                value={
                    "id": "660e9500-f39c-52e5-b827-557766551111",
                    "status": "pago",
                    "plano": "Pedido de Oração",
                    "valor_reais_str": "R$ 20,00",
                    "canal_entrega": "email",
                    "created_at": "2024-01-15T10:30:00Z",
                },
                response_only=True,
            ),
        ],
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)
