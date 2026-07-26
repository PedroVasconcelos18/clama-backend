"""
URLs da API de pedidos.
"""

from django.urls import path

from clama.orders.api.views import (
    DoacaoAnonimaCreateView,
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
    path("doacoes/", DoacaoAnonimaCreateView.as_view(), name="doacao-anonima-create"),
    path("pedidos/<uuid:id>/", PedidoStatusView.as_view(), name="pedido-status"),
]
