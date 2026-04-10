"""
Views da API de pedidos.
"""

from drf_spectacular.utils import OpenApiExample, OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.generics import CreateAPIView, RetrieveAPIView
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle

from clama.core.exceptions import PastoralAPIException
from clama.core.throttles import EmailScopedThrottle
from clama.orders.api.serializers import (
    PedidoCreateSerializer,
    PedidoResponseSerializer,
    PedidoStatusSerializer,
)
from clama.orders.models import Pedido


class PedidoCreateView(CreateAPIView):
    """
    Cria um novo pedido de oração.

    Recebe os dados do pedido e retorna o ID para prosseguir ao pagamento.
    Não requer autenticação.

    Rate limiting:
    - 10 requests/minuto por IP (ScopedRateThrottle)
    - 5 pedidos/hora por email (EmailScopedThrottle)
    """

    serializer_class = PedidoCreateSerializer
    permission_classes = [AllowAny]
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
