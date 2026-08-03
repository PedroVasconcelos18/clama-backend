"""
URLs do app core.
"""

from django.urls import path

from .views import CSRFTokenView, HealthCheckView

app_name = "core"

urlpatterns = [
    path("health/", HealthCheckView.as_view(), name="health"),
    path("csrf/", CSRFTokenView.as_view(), name="csrf"),
]
