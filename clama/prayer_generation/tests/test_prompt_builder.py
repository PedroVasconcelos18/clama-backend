"""
Testes para a função build_prompt.
"""
import pytest

from clama.orders.tests.factories import PedidoFactory
from clama.plans.models import Complexidade
from clama.plans.tests.factories import PlanFactory
from clama.prayer_generation.services.prompt_builder import build_prompt
from clama.prompts.tests.factories import PromptTemplateFactory


@pytest.fixture
def template_ativo():
    """Template de prompt ativo."""
    return PromptTemplateFactory(
        ativo=True,
        system_prompt="Sistema de oração pastoral.",
        instrucoes_por_complexidade={
            "simples": "Gere uma oração curta.",
            "com_versiculo": "Gere uma oração com versículo.",
            "com_profecia_e_versiculos": "Gere uma oração com profecia.",
        },
    )


@pytest.mark.django_db
class TestBuildPromptBasic:
    """Testes básicos do build_prompt."""

    def test_returns_tuple_of_strings(self, template_ativo):
        """build_prompt retorna tupla (system_prompt, user_message)."""
        pedido = PedidoFactory()
        result = build_prompt(pedido, template_ativo)

        assert isinstance(result, tuple)
        assert len(result) == 2
        assert isinstance(result[0], str)
        assert isinstance(result[1], str)

    def test_system_prompt_from_template(self, template_ativo):
        """system_prompt vem do template."""
        pedido = PedidoFactory()
        system_prompt, _ = build_prompt(pedido, template_ativo)

        assert system_prompt == "Sistema de oração pastoral."

    def test_user_message_contains_nome(self, template_ativo):
        """user_message contém o nome do pedido."""
        pedido = PedidoFactory(nome="Maria Silva")
        _, user_message = build_prompt(pedido, template_ativo)

        assert "Maria Silva" in user_message
        assert "Nome: Maria Silva" in user_message


@pytest.mark.django_db
class TestBuildPromptComplexidade:
    """Testes de complexidade."""

    def test_simples_uses_correct_instruction(self, template_ativo):
        """Pedido com plano SIMPLES usa instrução correta."""
        plano = PlanFactory(complexidade=Complexidade.SIMPLES)
        pedido = PedidoFactory(plano=plano)

        _, user_message = build_prompt(pedido, template_ativo)

        assert "Gere uma oração curta." in user_message

    def test_com_versiculo_uses_correct_instruction(self, template_ativo):
        """Pedido com plano COM_VERSICULO usa instrução correta."""
        plano = PlanFactory(complexidade=Complexidade.COM_VERSICULO)
        pedido = PedidoFactory(plano=plano)

        _, user_message = build_prompt(pedido, template_ativo)

        assert "Gere uma oração com versículo." in user_message

    def test_com_profecia_uses_correct_instruction(self, template_ativo):
        """Pedido com plano COM_PROFECIA_E_VERSICULOS usa instrução correta."""
        plano = PlanFactory(complexidade=Complexidade.COM_PROFECIA_E_VERSICULOS)
        pedido = PedidoFactory(plano=plano)

        _, user_message = build_prompt(pedido, template_ativo)

        assert "Gere uma oração com profecia." in user_message


@pytest.mark.django_db
class TestBuildPromptPedidoVazio:
    """Testes para pedido vazio (FR17)."""

    def test_empty_pedido_uses_marker(self, template_ativo):
        """Pedido vazio usa marker '[pedido vazio]'."""
        pedido = PedidoFactory(pedido_oracao="")
        _, user_message = build_prompt(pedido, template_ativo)

        assert "[pedido vazio]" in user_message

    def test_whitespace_only_pedido_uses_marker(self, template_ativo):
        """Pedido com apenas espaços usa marker '[pedido vazio]'."""
        pedido = PedidoFactory(pedido_oracao="   \n  ")
        _, user_message = build_prompt(pedido, template_ativo)

        assert "[pedido vazio]" in user_message

    def test_non_empty_pedido_shows_content(self, template_ativo):
        """Pedido com conteúdo mostra o conteúdo."""
        pedido = PedidoFactory(pedido_oracao="Peço oração pela minha família.")
        _, user_message = build_prompt(pedido, template_ativo)

        assert "Peço oração pela minha família." in user_message
        assert "[pedido vazio]" not in user_message


@pytest.mark.django_db
class TestBuildPromptOptionalFields:
    """Testes para campos opcionais."""

    def test_sexo_empty_shows_nao_informado(self, template_ativo):
        """Sexo vazio mostra 'não informado'."""
        pedido = PedidoFactory(sexo="")
        _, user_message = build_prompt(pedido, template_ativo)

        assert "Sexo: não informado" in user_message

    def test_sexo_feminino_shows_feminino(self, template_ativo):
        """Sexo feminino mostra 'feminino'."""
        pedido = PedidoFactory(sexo="feminino")
        _, user_message = build_prompt(pedido, template_ativo)

        assert "Sexo: feminino" in user_message

    def test_idade_null_shows_nao_informada(self, template_ativo):
        """Idade nula mostra 'não informada'."""
        pedido = PedidoFactory(idade=None)
        _, user_message = build_prompt(pedido, template_ativo)

        assert "Idade: não informada" in user_message

    def test_idade_shows_value(self, template_ativo):
        """Idade com valor mostra o valor."""
        pedido = PedidoFactory(idade=35)
        _, user_message = build_prompt(pedido, template_ativo)

        assert "Idade: 35" in user_message
