"""
Views da API de pedidos.
"""

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
from clama.orders.api.serializers import (
    PedidoCreateSerializer,
    PedidoGratuitoCreateSerializer,
    PedidoResponseSerializer,
    PedidoStatusSerializer,
)
from clama.orders.models import Pedido


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
