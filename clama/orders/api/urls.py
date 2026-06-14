"""
URLs da API de pedidos.
"""

from django.urls import path

from clama.orders.api.views import (
    PedidoCreateView,
    PedidoGratuitoCreateView,
    PedidoStatusView,
)

urlpatterns = [
    path("pedidos/", PedidoCreateView.as_view(), name="pedido-create"),
    path(
        "pedidos/gratuito/",
        PedidoGratuitoCreateView.as_view(),
        name="pedido-create-gratuito",
    ),
    path("pedidos/<uuid:id>/", PedidoStatusView.as_view(), name="pedido-status"),
]
