"""
URLs agregadas para API admin.

Reúne todos os endpoints admin em um único ponto.
"""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from clama.core.api.metrics_views import DistributionMetricsView, OverviewMetricsView
from clama.documents.api.admin_views import AdminDocumentoContextoViewSet
from clama.orders.api.admin_views import (
    AdminPedidoDetailView,
    AdminPedidoListView,
    AdminPedidoMarcarGratuitoView,
    AdminPedidoReenviarView,
)
from clama.plans.api.admin_views import AdminPlanViewSet
from clama.prompts.api.admin_views import AdminPromptTemplateViewSet
from clama_backend.users.api.admin_customer_views import (
    AdminCustomerDetailView,
    AdminCustomerListView,
)

app_name = "admin_api"

# Router para ViewSets
router = DefaultRouter()
router.register("admin/planos", AdminPlanViewSet, basename="admin-planos")
router.register("admin/prompts", AdminPromptTemplateViewSet, basename="admin-prompts")
router.register("admin/documentos", AdminDocumentoContextoViewSet, basename="admin-documentos")

urlpatterns = [
    # ViewSets
    path("", include(router.urls)),
    # Customers
    path("admin/customers/", AdminCustomerListView.as_view(), name="customers-list"),
    path(
        "admin/customers/<int:id>/",
        AdminCustomerDetailView.as_view(),
        name="customers-detail",
    ),
    # Pedidos
    path("admin/pedidos/", AdminPedidoListView.as_view(), name="pedidos-list"),
    path("admin/pedidos/<uuid:id>/", AdminPedidoDetailView.as_view(), name="pedidos-detail"),
    path("admin/pedidos/<uuid:id>/reenviar/", AdminPedidoReenviarView.as_view(), name="pedidos-reenviar"),
    path(
        "admin/pedidos/<uuid:id>/marcar-gratuito/",
        AdminPedidoMarcarGratuitoView.as_view(),
        name="pedidos-marcar-gratuito",
    ),
    # Métricas
    path("admin/metrics/overview/", OverviewMetricsView.as_view(), name="metrics-overview"),
    path("admin/metrics/distribution/", DistributionMetricsView.as_view(), name="metrics-distribution"),
]
