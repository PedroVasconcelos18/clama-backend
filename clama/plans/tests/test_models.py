"""
Testes para models do app plans.
"""
import pytest
from django.core.exceptions import ValidationError

from clama.plans.models import Complexidade, Plan

from .factories import PlanFactory


@pytest.mark.django_db
class TestPlanModel:
    """Testes para o modelo Plan."""

    def test_create_plan(self):
        """Deve criar um plano com sucesso."""
        plan = PlanFactory()
        assert plan.pk is not None
        assert plan.ativo is True

    def test_valor_minimo_validation(self):
        """Valor mínimo deve ser R$ 0,01 (1 centavo)."""
        plan = PlanFactory.build(valor_centavos=0)
        with pytest.raises(ValidationError) as exc_info:
            plan.full_clean()
        assert "valor_centavos" in str(exc_info.value)

    def test_valor_minimo_aceito(self):
        """Valor de exatamente R$ 0,01 deve ser aceito."""
        plan = PlanFactory.build(valor_centavos=1)
        plan.full_clean()  # Não deve lançar exceção

    def test_valor_reais_str_property(self):
        """Property valor_reais_str deve formatar corretamente."""
        plan = PlanFactory.build(valor_centavos=2000)
        assert plan.valor_reais_str == "R$ 20,00"

        plan2 = PlanFactory.build(valor_centavos=5000)
        assert plan2.valor_reais_str == "R$ 50,00"

        plan3 = PlanFactory.build(valor_centavos=10000)
        assert plan3.valor_reais_str == "R$ 100,00"

    def test_ordering_by_ordem(self):
        """Planos devem ser ordenados por campo ordem."""
        # Limpar planos existentes para teste isolado
        Plan.objects.all().delete()

        plan3 = PlanFactory(ordem=3)
        plan1 = PlanFactory(ordem=1)
        plan2 = PlanFactory(ordem=2)

        planos = list(Plan.objects.all())
        assert planos[0].ordem == 1
        assert planos[1].ordem == 2
        assert planos[2].ordem == 3

    def test_str_representation(self):
        """__str__ deve retornar nome e valor formatado."""
        plan = PlanFactory.build(nome="Teste", valor_centavos=5000)
        assert str(plan) == "Teste - R$ 50,00"

    def test_complexidade_choices(self):
        """Complexidade deve aceitar apenas valores válidos."""
        plan = PlanFactory.build(complexidade=Complexidade.COM_VERSICULO)
        plan.full_clean()  # Não deve lançar exceção

        plan2 = PlanFactory.build()
        plan2.complexidade = "valor_invalido"
        with pytest.raises(ValidationError):
            plan2.full_clean()
