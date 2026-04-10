"""
URLs da API de pagamentos.
"""

from django.urls import path

from clama.payments.api.views import CheckoutView
from clama.payments.api.webhooks import AsaasWebhookView

urlpatterns = [
    path("pedidos/<uuid:id>/checkout/", CheckoutView.as_view(), name="pedido-checkout"),
    path("webhooks/asaas/", AsaasWebhookView.as_view(), name="asaas-webhook"),
]
