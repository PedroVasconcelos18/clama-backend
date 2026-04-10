"""
URLs da API de autenticação admin.
"""

from django.urls import path

from clama_backend.users.api.views import AdminLoginView, AdminTokenRefreshView

app_name = "users"

urlpatterns = [
    path("admin/auth/login/", AdminLoginView.as_view(), name="admin-login"),
    path("admin/auth/refresh/", AdminTokenRefreshView.as_view(), name="admin-refresh"),
]
