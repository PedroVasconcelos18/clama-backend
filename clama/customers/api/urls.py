"""
URLs da API customer-facing — montadas em `/api/customer/` pelo
`config/urls.py`.
"""

from django.urls import path

from clama.customers.api.views import (
    ChangePasswordView,
    CustomerLoginView,
    CustomerLogoutView,
    CustomerMeView,
    CustomerPedidosListView,
    CustomerRefreshView,
)

app_name = "customers"

urlpatterns = [
    path("auth/login/", CustomerLoginView.as_view(), name="login"),
    path("auth/refresh/", CustomerRefreshView.as_view(), name="refresh"),
    path("auth/logout/", CustomerLogoutView.as_view(), name="logout"),
    path(
        "auth/change-password/",
        ChangePasswordView.as_view(),
        name="change-password",
    ),
    path("me/", CustomerMeView.as_view(), name="me"),
    path("pedidos/", CustomerPedidosListView.as_view(), name="pedidos"),
]
