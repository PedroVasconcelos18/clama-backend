"""
Views da API de planos.
"""

from drf_spectacular.utils import OpenApiExample, extend_schema
from rest_framework.generics import ListAPIView
from rest_framework.permissions import AllowAny
from rest_framework.throttling import AnonRateThrottle

from clama.plans.api.serializers import PlanSerializer
from clama.plans.models import Plan


class PlanListView(ListAPIView):
    """
    Lista os planos de oração ativos.

    Retorna todos os planos disponíveis para compra, ordenados por ordem de exibição.
    Não requer autenticação.
    """

    serializer_class = PlanSerializer
    permission_classes = [AllowAny]
    throttle_classes = [AnonRateThrottle]
    pagination_class = None

    def get_queryset(self):
        # Lista apenas planos visíveis — oculta o "Gratuito" do fluxo
        # freemium, que é selecionado por endpoint dedicado.
        return Plan.objects.filter(ativo=True, visivel=True).order_by("ordem")

    @extend_schema(
        tags=["Planos"],
        summary="Listar planos de oração",
        description="Retorna a lista de planos ativos ordenados por ordem de exibição.",
        examples=[
            OpenApiExample(
                "Exemplo de resposta",
                value=[
                    {
                        "id": "550e8400-e29b-41d4-a716-446655440000",
                        "nome": "Pedido de Oração",
                        "valor_centavos": 2000,
                        "valor_reais_str": "R$ 20,00",
                        "descricao": "Uma oração pessoal e acolhedora.",
                        "complexidade": "simples",
                        "ordem": 1,
                    },
                    {
                        "id": "550e8400-e29b-41d4-a716-446655440001",
                        "nome": "Pedido + Versículo",
                        "valor_centavos": 3000,
                        "valor_reais_str": "R$ 30,00",
                        "descricao": "Oração + versículo bíblico relevante.",
                        "complexidade": "com_versiculo",
                        "ordem": 2,
                    },
                ],
                response_only=True,
            ),
        ],
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)
