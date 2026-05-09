"""
URLs da API freemium.

Pós-renegociação 2026-05-08: a rota `/freemium/otp/enviar/` foi removida
(sem OTP) e substituída pelo endpoint de confirmação por e-mail
`/freemium/confirmar/` (double opt-in).
"""

from django.urls import path

from clama.freemium.api.views import (
    FreemiumConfirmarView,
    PedidoFreemiumCreateView,
)

urlpatterns = [
    path(
        "freemium/pedidos/",
        PedidoFreemiumCreateView.as_view(),
        name="freemium-pedido-create",
    ),
    path(
        "freemium/confirmar/",
        FreemiumConfirmarView.as_view(),
        name="freemium-confirmar",
    ),
]
