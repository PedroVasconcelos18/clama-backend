"""
Testes para a API de planos.
"""
import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from clama.plans.models import Plan
from clama.plans.tests.factories import PlanFactory


@pytest.fixture
def api_client():
    """API client para testes."""
    return APIClient()


@pytest.mark.django_db
class TestPlanListAPI:
    """Testes para GET /api/planos/."""

    def test_list_plans_returns_200_without_auth(self, api_client):
        """Endpoint deve retornar 200 sem autenticação."""
        # Limpar planos existentes do seed
        Plan.objects.all().delete()
        PlanFactory(ativo=True)

        url = reverse("plan-list")
        response = api_client.get(url)

        assert response.status_code == status.HTTP_200_OK

    def test_list_plans_returns_seeded_plans(self, api_client):
        """Endpoint deve retornar os 3 planos seedados."""
        url = reverse("plan-list")
        response = api_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 3

    def test_list_plans_excludes_inactive(self, api_client):
        """Planos inativos não devem aparecer na lista."""
        # Limpar planos existentes
        Plan.objects.all().delete()

        PlanFactory(ativo=True, ordem=1)
        PlanFactory(ativo=True, ordem=2)
        PlanFactory(ativo=False, ordem=3)

        url = reverse("plan-list")
        response = api_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 2

    def test_list_plans_ordered_by_ordem(self, api_client):
        """Planos devem vir ordenados pelo campo ordem."""
        # Limpar planos existentes
        Plan.objects.all().delete()

        PlanFactory(nome="Terceiro", ordem=3, ativo=True)
        PlanFactory(nome="Primeiro", ordem=1, ativo=True)
        PlanFactory(nome="Segundo", ordem=2, ativo=True)

        url = reverse("plan-list")
        response = api_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert response.data[0]["nome"] == "Primeiro"
        assert response.data[1]["nome"] == "Segundo"
        assert response.data[2]["nome"] == "Terceiro"

    def test_list_plans_response_format(self, api_client):
        """Resposta deve ter o formato correto."""
        # Usar os planos seedados
        url = reverse("plan-list")
        response = api_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) > 0

        plan_data = response.data[0]
        assert "id" in plan_data
        assert "nome" in plan_data
        assert "valor_centavos" in plan_data
        assert "valor_reais_str" in plan_data
        assert "descricao" in plan_data
        assert "complexidade" in plan_data
        assert "ordem" in plan_data

        # Não deve expor ativo nem timestamps
        assert "ativo" not in plan_data
        assert "created_at" not in plan_data
        assert "updated_at" not in plan_data

    def test_list_plans_valor_reais_str_format(self, api_client):
        """valor_reais_str deve estar formatado corretamente."""
        # Limpar e criar plano com valor conhecido
        Plan.objects.all().delete()
        PlanFactory(valor_centavos=2500, ativo=True)

        url = reverse("plan-list")
        response = api_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert response.data[0]["valor_reais_str"] == "R$ 25,00"

    def test_list_plans_returns_array_not_paginated(self, api_client):
        """Resposta deve ser array direto, não paginado."""
        url = reverse("plan-list")
        response = api_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        # Array direto, não dict com 'results'
        assert isinstance(response.data, list)

    def test_list_plans_complexidade_in_snake_case(self, api_client):
        """Complexidade deve vir em snake_case."""
        url = reverse("plan-list")
        response = api_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        # Verificar que não está em UPPERCASE
        for plan in response.data:
            complexidade = plan["complexidade"]
            assert complexidade == complexidade.lower()
