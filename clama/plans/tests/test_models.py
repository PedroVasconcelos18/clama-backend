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


@pytest.mark.django_db
class TestPlanManagerInferFromValor:
    """Testes para PlanManager.infer_from_valor ("par abaixo")."""

    @pytest.fixture
    def tres_planos(self):
        """Três planos ativos: R$20 (SIMPLES), R$50 (COM_VERSICULO), R$100."""
        Plan.objects.all().delete()
        simples = PlanFactory(
            nome="Simples",
            valor_centavos=2000,
            complexidade=Complexidade.SIMPLES,
            ordem=1,
            ativo=True,
        )
        com_versiculo = PlanFactory(
            nome="Com versículo",
            valor_centavos=5000,
            complexidade=Complexidade.COM_VERSICULO,
            ordem=2,
            ativo=True,
        )
        com_profecia = PlanFactory(
            nome="Com profecia",
            valor_centavos=10000,
            complexidade=Complexidade.COM_PROFECIA_E_VERSICULOS,
            ordem=3,
            ativo=True,
        )
        return simples, com_versiculo, com_profecia

    def test_valor_exato_retorna_mesmo_plano(self, tres_planos):
        """Valor exato deve retornar o plano correspondente."""
        simples, com_versiculo, com_profecia = tres_planos
        assert Plan.objects.infer_from_valor(2000) == simples
        assert Plan.objects.infer_from_valor(5000) == com_versiculo
        assert Plan.objects.infer_from_valor(10000) == com_profecia

    def test_valor_entre_planos_retorna_par_abaixo(self, tres_planos):
        """Valor entre dois planos deve retornar o plano inferior."""
        simples, com_versiculo, com_profecia = tres_planos
        # R$35 → SIMPLES (R$20)
        assert Plan.objects.infer_from_valor(3500) == simples
        # R$75 → COM_VERSICULO (R$50)
        assert Plan.objects.infer_from_valor(7500) == com_versiculo
        # R$150 → COM_PROFECIA (R$100)
        assert Plan.objects.infer_from_valor(15000) == com_profecia

    def test_valor_muito_acima_retorna_plano_maior(self, tres_planos):
        """Valor muito acima do maior plano continua no plano maior."""
        _, _, com_profecia = tres_planos
        assert Plan.objects.infer_from_valor(500000) == com_profecia

    def test_valor_abaixo_do_minimo_retorna_menor_plano(self, tres_planos):
        """Fallback: valor < menor plano retorna o menor ativo."""
        simples, _, _ = tres_planos
        # R$5 < R$20: serializer já valida antes, mas manager deve não quebrar.
        assert Plan.objects.infer_from_valor(500) == simples

    def test_ignora_planos_inativos(self, tres_planos):
        """Planos inativos não devem ser considerados."""
        simples, com_versiculo, com_profecia = tres_planos
        com_profecia.ativo = False
        com_profecia.save()
        # R$150 não encontra COM_PROFECIA inativo → cai para COM_VERSICULO
        assert Plan.objects.infer_from_valor(15000) == com_versiculo

    def test_sem_planos_ativos_retorna_none(self):
        """Sem planos ativos retorna None."""
        Plan.objects.all().delete()
        assert Plan.objects.infer_from_valor(5000) is None


@pytest.mark.django_db
class TestPlanManagerFallbackValorLivre:
    """Testes para PlanManager.fallback_valor_livre (plano interno "Livre")."""

    def test_retorna_plano_simples_invisivel_ativo(self):
        """Retorna o plano simples, invisível e ativo (o fallback do valor livre)."""
        Plan.objects.all().delete()
        livre = PlanFactory(
            nome="Livre",
            complexidade=Complexidade.SIMPLES,
            ativo=True,
            visivel=False,
        )
        assert Plan.objects.fallback_valor_livre() == livre

    def test_ignora_tier_simples_visivel(self):
        """O tier "simples" visível NÃO é o fallback (só o invisível)."""
        Plan.objects.all().delete()
        PlanFactory(
            nome="Pedido de Oração",
            complexidade=Complexidade.SIMPLES,
            ativo=True,
            visivel=True,
        )
        assert Plan.objects.fallback_valor_livre() is None

    def test_ignora_fallback_inativo(self):
        """Fallback inativo não é retornado."""
        Plan.objects.all().delete()
        PlanFactory(
            nome="Livre",
            complexidade=Complexidade.SIMPLES,
            ativo=False,
            visivel=False,
        )
        assert Plan.objects.fallback_valor_livre() is None

    def test_sem_fallback_retorna_none(self):
        """Sem nenhum plano retorna None."""
        Plan.objects.all().delete()
        assert Plan.objects.fallback_valor_livre() is None
