"""
URLs da API de pagamentos.
"""

from django.urls import path

from clama.payments.api.views import CheckoutView
from clama.payments.api.webhooks import MercadoPagoWebhookView

urlpatterns = [
    path("pedidos/<uuid:id>/checkout/", CheckoutView.as_view(), name="pedido-checkout"),
    path(
        "webhooks/mercadopago/",
        MercadoPagoWebhookView.as_view(),
        name="mercadopago-webhook",
    ),
]
