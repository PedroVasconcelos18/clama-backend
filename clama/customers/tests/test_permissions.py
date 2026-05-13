"""
Testes de `IsCustomerPasswordCurrent` em [clama/core/permissions.py](../../core/permissions.py).
"""

import pytest
from django.contrib.auth import get_user_model
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.test import APIClient
from rest_framework.views import APIView
from django.urls import path

from clama.core.permissions import IsCustomerPasswordCurrent

User = get_user_model()


class _ProtectedView(APIView):
    permission_classes = [IsAuthenticated, IsCustomerPasswordCurrent]

    def get(self, request):
        return Response({"ok": True})


urlpatterns = [path("__test__/protected/", _ProtectedView.as_view())]


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def customer(db):
    return User.objects.create_user(
        email="customer@example.com", password="Senha-Forte-12345!"
    )


@pytest.fixture
def customer_force(db):
    return User.objects.create_user(
        email="force@example.com",
        password="Temp-Pass-1234!",
        force_change_password=True,
    )


@pytest.mark.django_db
@pytest.mark.urls(__name__)
class TestIsCustomerPasswordCurrent:
    def test_anonimo_retorna_401_pelo_isauthenticated(self, api_client):
        resp = api_client.get("/__test__/protected/")
        assert resp.status_code == 401

    def test_autenticado_normal_passa(self, api_client, customer):
        api_client.force_authenticate(user=customer)
        resp = api_client.get("/__test__/protected/")
        assert resp.status_code == 200
        assert resp.data == {"ok": True}

    def test_autenticado_com_force_change_password_recebe_403(
        self, api_client, customer_force
    ):
        api_client.force_authenticate(user=customer_force)
        resp = api_client.get("/__test__/protected/")
        assert resp.status_code == 403
        assert resp.data["error"]["code"] == "customer_force_change_password"
