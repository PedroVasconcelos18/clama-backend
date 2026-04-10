"""
URLs da API de notificações.
"""

from django.urls import path

from clama.notifications.api.webhooks import ZapiWebhookView

app_name = "notifications"

urlpatterns = [
    path("webhooks/zapi/", ZapiWebhookView.as_view(), name="webhook-zapi"),
]
