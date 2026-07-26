"""
Testes do serviço de repasse (cálculo, snapshot e idempotência).
"""

import pytest

from clama.instituicoes.models import Repasse, RepasseStatus
from clama.instituicoes.services.repasse import registrar_repasse
from clama.instituicoes.tests.factories import InstituicaoFactory
from clama.orders.tests.factories import PedidoFactory


@pytest.mark.django_db
class TestRegistrarRepasse:
    def test_calcula_20_porcento_com_snapshot(self):
        instituicao = InstituicaoFactory()
        pedido = PedidoFactory(valor_centavos=5000, instituicao=instituicao)

        repasse = registrar_repasse(pedido)

        assert repasse is not None
        assert repasse.valor_centavos == 1000
        assert repasse.percentual == 20
        assert repasse.valor_base_centavos == 5000
        assert repasse.instituicao_id == instituicao.id
        assert repasse.status == RepasseStatus.REGISTRADO

    def test_chamar_duas_vezes_nao_duplica(self):
        instituicao = InstituicaoFactory()
        pedido = PedidoFactory(valor_centavos=5000, instituicao=instituicao)

        primeiro = registrar_repasse(pedido)
        segundo = registrar_repasse(pedido)

        assert primeiro.id == segundo.id
        assert Repasse.objects.filter(pedido=pedido).count() == 1

    def test_pedido_sem_instituicao_retorna_none(self):
        pedido = PedidoFactory(instituicao=None)

        assert registrar_repasse(pedido) is None
        assert Repasse.objects.count() == 0

    def test_calculo_usa_piso_inteiro(self):
        instituicao = InstituicaoFactory()
        pedido = PedidoFactory(valor_centavos=999, instituicao=instituicao)

        repasse = registrar_repasse(pedido)

        # 999 * 20 // 100 = 199 (piso inteiro, nunca float/Decimal)
        assert repasse.valor_centavos == 199
