"""
Factories para testes do app instituicoes.
"""

import factory
from factory.django import DjangoModelFactory

from clama.instituicoes.models import Instituicao, Repasse, RepasseStatus
from clama.orders.tests.factories import PedidoFactory


class InstituicaoFactory(DjangoModelFactory):
    class Meta:
        model = Instituicao

    nome = factory.Sequence(lambda n: f"Instituição {n}")
    logo = ""
    ativo = True
    ordem = factory.Sequence(lambda n: n + 1)


class RepasseFactory(DjangoModelFactory):
    class Meta:
        model = Repasse

    pedido = factory.SubFactory(PedidoFactory)
    instituicao = factory.SubFactory(InstituicaoFactory)
    valor_base_centavos = 5000
    percentual = 20
    valor_centavos = 1000
    status = RepasseStatus.REGISTRADO
