"""
Views de métricas para dashboard admin.
"""

from datetime import timedelta

from django.db.models import Count, Sum
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework.response import Response

from clama.core.api.admin_base import AdminAPIView
from clama.core.exceptions import PastoralAPIException
from clama.core.money import centavos_to_reais_str
from clama.orders.models import Pedido, PedidoStatus


def _get_period_range(period: str):
    """Retorna (start, end) para o período especificado."""
    now = timezone.now()

    if period == "day":
        start = now - timedelta(hours=24)
        end = now
    elif period == "week":
        start = now - timedelta(days=7)
        end = now
    elif period == "month":
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        # Último dia do mês
        next_month = start.replace(month=start.month % 12 + 1) if start.month < 12 else start.replace(year=start.year + 1, month=1)
        end = next_month - timedelta(seconds=1)
    else:
        return None, None

    return start, end


class OverviewMetricsView(AdminAPIView):
    """
    Métricas de visão geral do dashboard.

    Retorna contagens de pedidos e faturamento para o período especificado.
    """

    @method_decorator(cache_page(60))  # Cache de 60 segundos
    @extend_schema(
        tags=["Admin / Metrics"],
        summary="Métricas de overview",
        description="""
Retorna métricas agregadas para o período especificado.

**Períodos válidos:**
- `day`: Últimas 24 horas
- `week`: Últimos 7 dias
- `month`: Mês corrente

**Cache:** 60 segundos
        """,
        parameters=[
            OpenApiParameter(
                name="period",
                description="Período (day, week, month)",
                default="month",
            ),
        ],
        responses={
            200: OpenApiResponse(description="Métricas de overview"),
            400: OpenApiResponse(description="Período inválido"),
            401: OpenApiResponse(description="Não autenticado"),
            403: OpenApiResponse(description="Não é admin"),
        },
    )
    def get(self, request):
        period = request.query_params.get("period", "month")

        start, end = _get_period_range(period)
        if start is None:
            raise PastoralAPIException(
                code="invalid_period",
                message="Período inválido",
                pastoral_message="Período não reconhecido. Use: day, week ou month.",
                status_code=400,
            )

        # Query base
        pedidos = Pedido.objects.filter(created_at__range=(start, end))

        # Contagens por status
        pedidos_total = pedidos.count()
        pedidos_pagos = pedidos.exclude(status=PedidoStatus.AGUARDANDO_PAGAMENTO).count()
        pedidos_enviadas = pedidos.filter(status=PedidoStatus.ENVIADA).count()
        pedidos_erro = pedidos.filter(
            status__in=[PedidoStatus.ERRO, PedidoStatus.AGUARDANDO_REENVIO]
        ).count()

        # Faturamento (apenas pedidos que passaram de AGUARDANDO_PAGAMENTO)
        faturamento = pedidos.exclude(
            status=PedidoStatus.AGUARDANDO_PAGAMENTO
        ).aggregate(total=Sum("valor_centavos"))
        faturamento_centavos = faturamento["total"] or 0

        # Ticket médio
        ticket_medio = faturamento_centavos // pedidos_pagos if pedidos_pagos > 0 else 0

        return Response({
            "period": period,
            "range": {
                "start": start.isoformat(),
                "end": end.isoformat(),
            },
            "pedidos_total": pedidos_total,
            "pedidos_pagos": pedidos_pagos,
            "pedidos_enviadas": pedidos_enviadas,
            "pedidos_erro": pedidos_erro,
            "faturamento_centavos": faturamento_centavos,
            "faturamento_reais_str": centavos_to_reais_str(faturamento_centavos),
            "ticket_medio_centavos": ticket_medio,
        })


class DistributionMetricsView(AdminAPIView):
    """
    Métricas de distribuição para dashboard.

    Retorna distribuição por plano, canal e lista de alertas (pedidos com erro).
    """

    @method_decorator(cache_page(60))  # Cache de 60 segundos
    @extend_schema(
        tags=["Admin / Metrics"],
        summary="Métricas de distribuição",
        description="""
Retorna distribuição de pedidos por plano e canal, além de alertas de erro.

**Períodos válidos:**
- `day`: Últimas 24 horas
- `week`: Últimos 7 dias
- `month`: Mês corrente

**Cache:** 60 segundos
        """,
        parameters=[
            OpenApiParameter(
                name="period",
                description="Período (day, week, month)",
                default="month",
            ),
        ],
        responses={
            200: OpenApiResponse(description="Métricas de distribuição"),
            400: OpenApiResponse(description="Período inválido"),
            401: OpenApiResponse(description="Não autenticado"),
            403: OpenApiResponse(description="Não é admin"),
        },
    )
    def get(self, request):
        period = request.query_params.get("period", "month")

        start, end = _get_period_range(period)
        if start is None:
            raise PastoralAPIException(
                code="invalid_period",
                message="Período inválido",
                pastoral_message="Período não reconhecido. Use: day, week ou month.",
                status_code=400,
            )

        # Query base (apenas pagos)
        pedidos = Pedido.objects.filter(
            created_at__range=(start, end)
        ).exclude(status=PedidoStatus.AGUARDANDO_PAGAMENTO)

        total = pedidos.count()

        # Distribuição por plano
        dist_plano = pedidos.values(
            "plano__nome", "plano__valor_centavos"
        ).annotate(count=Count("id")).order_by("-count")

        distribuicao_por_plano = [
            {
                "plano_nome": item["plano__nome"],
                "valor_centavos": item["plano__valor_centavos"],
                "count": item["count"],
                "pct": round(item["count"] * 100 / total, 1) if total > 0 else 0,
            }
            for item in dist_plano
        ]

        # Distribuição por canal
        dist_canal = pedidos.values("canal_entrega").annotate(count=Count("id"))
        distribuicao_por_canal = [
            {"canal": item["canal_entrega"].upper(), "count": item["count"]}
            for item in dist_canal
        ]

        # Alertas (pedidos com erro ou aguardando reenvio)
        alertas = Pedido.objects.filter(
            status__in=[PedidoStatus.ERRO, PedidoStatus.AGUARDANDO_REENVIO]
        ).select_related("plano").order_by("-created_at")[:20]

        alertas_erro = [
            {
                "id": str(p.id),
                "created_at": p.created_at.isoformat(),
                "nome": p.nome[:20] + "..." if len(p.nome) > 20 else p.nome,
                "plano": p.plano.nome,
                "status": p.status.upper(),
                "last_error": p.last_error[:100] if p.last_error else "",
            }
            for p in alertas
        ]

        return Response({
            "distribuicao_por_plano": distribuicao_por_plano,
            "distribuicao_por_canal": distribuicao_por_canal,
            "alertas_erro": alertas_erro,
        })
