"""
Factories para testes do app orders.
"""
import factory
from factory.django import DjangoModelFactory

from clama.orders.models import CanalEntrega, Pedido, PedidoStatus
from clama.plans.tests.factories import PlanFactory


class PedidoFactory(DjangoModelFactory):
    class Meta:
        model = Pedido

    nome = factory.Faker("name", locale="pt_BR")
    email = factory.Faker("email")
    telefone = factory.Faker("phone_number", locale="pt_BR")
    idade = factory.Faker("pyint", min_value=18, max_value=80)
    sexo = ""
    pedido_oracao = factory.Faker("paragraph", locale="pt_BR")
    oracao_gerada = ""
    plano = factory.SubFactory(PlanFactory)
    valor_centavos = factory.LazyAttribute(lambda o: o.plano.valor_centavos)
    canal_entrega = CanalEntrega.EMAIL
    status = PedidoStatus.AGUARDANDO_PAGAMENTO
    asaas_charge_id = ""
    asaas_invoice_url = ""
