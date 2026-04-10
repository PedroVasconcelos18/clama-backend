"""
Testes para os models do app orders.
"""
import pytest

from clama.core.exceptions import PastoralAPIException
from clama.orders.models import CanalEntrega, Pedido, PedidoStatus, Sexo
from clama.orders.tests.factories import PedidoFactory
from clama.plans.tests.factories import PlanFactory


@pytest.mark.django_db
class TestPedidoModel:
    """Testes para o model Pedido."""

    def test_create_pedido_with_default_status(self):
        """Criar pedido deve ter status AGUARDANDO_PAGAMENTO por default."""
        pedido = PedidoFactory()
        assert pedido.status == PedidoStatus.AGUARDANDO_PAGAMENTO

    def test_pedido_has_uuid_pk(self):
        """Pedido deve ter UUID como PK."""
        pedido = PedidoFactory()
        assert pedido.id is not None
        assert len(str(pedido.id)) == 36  # UUID format

    def test_pedido_has_timestamps(self):
        """Pedido deve ter created_at e updated_at."""
        pedido = PedidoFactory()
        assert pedido.created_at is not None
        assert pedido.updated_at is not None

    def test_pedido_str_representation(self):
        """__str__ deve retornar identificador do pedido."""
        pedido = PedidoFactory(nome="Maria Silva")
        assert "Maria Silva" in str(pedido)
        assert "Pedido" in str(pedido)

    def test_valor_reais_str_property(self):
        """valor_reais_str deve retornar valor formatado em reais."""
        plano = PlanFactory(valor_centavos=5000)
        pedido = PedidoFactory(plano=plano, valor_centavos=5000)
        assert pedido.valor_reais_str == "R$ 50,00"


@pytest.mark.django_db
class TestPedidoMarcarComoPago:
    """Testes para o método marcar_como_pago."""

    def test_marcar_como_pago_valid_transition(self):
        """marcar_como_pago deve transicionar de AGUARDANDO_PAGAMENTO para PAGO."""
        pedido = PedidoFactory(status=PedidoStatus.AGUARDANDO_PAGAMENTO)
        pedido.marcar_como_pago()
        pedido.refresh_from_db()
        assert pedido.status == PedidoStatus.PAGO

    def test_marcar_como_pago_already_pago_raises(self):
        """marcar_como_pago em pedido PAGO deve levantar exceção."""
        pedido = PedidoFactory()
        pedido.status = PedidoStatus.PAGO
        pedido.save()

        with pytest.raises(PastoralAPIException) as exc_info:
            pedido.marcar_como_pago()

        assert exc_info.value.code == "invalid_state_transition"
        assert exc_info.value.status_code == 409

    def test_marcar_como_pago_enviada_raises(self):
        """marcar_como_pago em pedido ENVIADA deve levantar exceção."""
        pedido = PedidoFactory()
        pedido.status = PedidoStatus.ENVIADA
        pedido.save()

        with pytest.raises(PastoralAPIException) as exc_info:
            pedido.marcar_como_pago()

        assert exc_info.value.code == "invalid_state_transition"


@pytest.mark.django_db
class TestPedidoCamposCriptografados:
    """Testes para campos criptografados do Pedido."""

    def test_encrypted_email_roundtrip(self):
        """Email criptografado deve gravar e ler corretamente."""
        test_email = "juliana.teste@example.com"
        pedido = PedidoFactory(email=test_email)
        pedido.save()

        pedido.refresh_from_db()
        assert pedido.email == test_email

    def test_encrypted_nome_roundtrip(self):
        """Nome criptografado deve gravar e ler corretamente."""
        test_nome = "Juliana da Silva Santos"
        pedido = PedidoFactory(nome=test_nome)
        pedido.save()

        pedido.refresh_from_db()
        assert pedido.nome == test_nome

    def test_encrypted_telefone_roundtrip(self):
        """Telefone criptografado deve gravar e ler corretamente."""
        test_telefone = "(11) 99999-8888"
        pedido = PedidoFactory(telefone=test_telefone)
        pedido.save()

        pedido.refresh_from_db()
        assert pedido.telefone == test_telefone

    def test_encrypted_pedido_oracao_roundtrip(self):
        """Pedido de oração criptografado deve gravar e ler corretamente."""
        test_pedido = "Peço oração pela minha família e pela saúde da minha mãe."
        pedido = PedidoFactory(pedido_oracao=test_pedido)
        pedido.save()

        pedido.refresh_from_db()
        assert pedido.pedido_oracao == test_pedido

    def test_encrypted_oracao_gerada_roundtrip(self):
        """Oração gerada criptografada deve gravar e ler corretamente."""
        test_oracao = "Senhor, abençoa esta família com Tua paz e graça infinitas..."
        pedido = PedidoFactory(oracao_gerada=test_oracao)
        pedido.save()

        pedido.refresh_from_db()
        assert pedido.oracao_gerada == test_oracao


@pytest.mark.django_db
class TestPedidoEnums:
    """Testes para os enums do Pedido."""

    def test_sexo_choices(self):
        """Sexo deve ter as opções corretas."""
        assert Sexo.FEMININO == "feminino"
        assert Sexo.MASCULINO == "masculino"
        assert Sexo.NAO_INFORMADO == "nao_informado"

    def test_canal_entrega_choices(self):
        """CanalEntrega deve ter as opções corretas."""
        assert CanalEntrega.EMAIL == "email"
        assert CanalEntrega.WHATSAPP == "whatsapp"

    def test_pedido_status_choices(self):
        """PedidoStatus deve ter as opções corretas."""
        assert PedidoStatus.AGUARDANDO_PAGAMENTO == "aguardando_pagamento"
        assert PedidoStatus.PAGO == "pago"
        assert PedidoStatus.GERANDO_ORACAO == "gerando_oracao"
        assert PedidoStatus.ORACAO_GERADA == "oracao_gerada"
        assert PedidoStatus.ENVIADA == "enviada"
        assert PedidoStatus.ERRO == "erro"

    def test_pedido_with_sexo_feminino(self):
        """Pedido deve aceitar sexo feminino."""
        pedido = PedidoFactory(sexo=Sexo.FEMININO)
        pedido.refresh_from_db()
        assert pedido.sexo == Sexo.FEMININO

    def test_pedido_with_canal_whatsapp(self):
        """Pedido deve aceitar canal WhatsApp."""
        pedido = PedidoFactory(canal_entrega=CanalEntrega.WHATSAPP)
        pedido.refresh_from_db()
        assert pedido.canal_entrega == CanalEntrega.WHATSAPP


@pytest.mark.django_db
class TestPedidoPlanoRelationship:
    """Testes para relacionamento Pedido-Plano."""

    def test_pedido_has_plano(self):
        """Pedido deve ter relacionamento com Plano."""
        plano = PlanFactory(nome="Plano Premium")
        pedido = PedidoFactory(plano=plano)
        assert pedido.plano == plano
        assert pedido.plano.nome == "Plano Premium"

    def test_plano_has_pedidos_related_name(self):
        """Plano deve ter acesso a pedidos via related_name."""
        plano = PlanFactory()
        pedido = PedidoFactory(plano=plano)
        assert plano.pedidos.count() == 1
        assert plano.pedidos.first() == pedido
