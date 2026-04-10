"""
Factories para testes do app plans.
"""
import factory
from factory.django import DjangoModelFactory

from clama.plans.models import Complexidade, Plan


class PlanFactory(DjangoModelFactory):
    class Meta:
        model = Plan

    nome = factory.Sequence(lambda n: f"Plano {n}")
    valor_centavos = 2000
    descricao = "Descrição do plano de teste"
    complexidade = Complexidade.SIMPLES
    ordem = factory.Sequence(lambda n: n + 1)
    ativo = True
