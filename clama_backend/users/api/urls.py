"""
URLs da API de autenticação admin e customer.
"""

from django.urls import path

from clama_backend.users.api.views import (
    AdminLoginView,
    AdminTokenRefreshView,
    CustomerChangePasswordView,
    CustomerLoginView,
    CustomerLogoutView,
    CustomerMeView,
    CustomerTokenRefreshView,
)

app_name = "users"

urlpatterns = [
    # Admin auth (existente)
    path("admin/auth/login/", AdminLoginView.as_view(), name="admin-login"),
    path("admin/auth/refresh/", AdminTokenRefreshView.as_view(), name="admin-refresh"),
    # Customer auth (G2.a)
    path(
        "customer/auth/login/",
        CustomerLoginView.as_view(),
        name="customer-login",
    ),
    path(
        "customer/auth/refresh/",
        CustomerTokenRefreshView.as_view(),
        name="customer-refresh",
    ),
    path(
        "customer/auth/logout/",
        CustomerLogoutView.as_view(),
        name="customer-logout",
    ),
    path(
        "customer/auth/change-password/",
        CustomerChangePasswordView.as_view(),
        name="customer-change-password",
    ),
    path(
        "customer/me/",
        CustomerMeView.as_view(),
        name="customer-me",
    ),
]
