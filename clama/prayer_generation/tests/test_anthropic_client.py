"""
Testes para o AnthropicClient.
"""
from unittest.mock import MagicMock, patch

import anthropic
import pytest

from clama.orders.tests.factories import PedidoFactory
from clama.plans.models import Complexidade
from clama.plans.tests.factories import PlanFactory
from clama.prayer_generation.exceptions import PrayerGenerationError
from clama.prayer_generation.services.anthropic_client import AnthropicClient
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


@pytest.fixture
def pedido(template_ativo):
    """Pedido de oração."""
    plano = PlanFactory(complexidade=Complexidade.SIMPLES)
    return PedidoFactory(
        nome="Maria Silva",
        pedido_oracao="Peço oração pela minha família.",
        plano=plano,
    )


@pytest.fixture
def mock_anthropic_response():
    """Mock de resposta da API Anthropic."""
    response = MagicMock()
    response.content = [MagicMock(text="Querida Maria, que Deus abençoe...")]
    response.usage = MagicMock(output_tokens=150)
    return response


@pytest.mark.django_db
class TestAnthropicClientHappyPath:
    """Testes do fluxo feliz do AnthropicClient."""

    def test_gerar_oracao_returns_string(
        self, pedido, template_ativo, mock_anthropic_response
    ):
        """gerar_oracao retorna string com a oração."""
        with patch("clama.prayer_generation.services.anthropic_client.anthropic.Anthropic") as mock_class:
            mock_client = MagicMock()
            mock_client.messages.create.return_value = mock_anthropic_response
            mock_class.return_value = mock_client

            client = AnthropicClient()
            result = client.gerar_oracao(pedido)

        assert isinstance(result, str)
        assert "Querida Maria" in result

    def test_gerar_oracao_calls_api_with_correct_params(
        self, pedido, template_ativo, mock_anthropic_response
    ):
        """gerar_oracao chama a API com parâmetros corretos."""
        with patch("clama.prayer_generation.services.anthropic_client.anthropic.Anthropic") as mock_class:
            mock_client = MagicMock()
            mock_client.messages.create.return_value = mock_anthropic_response
            mock_class.return_value = mock_client

            client = AnthropicClient()
            client.gerar_oracao(pedido)

        # Verifica chamada da API
        mock_client.messages.create.assert_called_once()
        call_kwargs = mock_client.messages.create.call_args[1]

        assert call_kwargs["model"] == "claude-sonnet-4-20250514"
        assert call_kwargs["max_tokens"] == 1500
        assert call_kwargs["timeout"] == 30.0
        assert "system" in call_kwargs
        assert "messages" in call_kwargs

    def test_gerar_oracao_uses_active_template(
        self, pedido, template_ativo, mock_anthropic_response
    ):
        """gerar_oracao usa o template ativo."""
        with patch("clama.prayer_generation.services.anthropic_client.anthropic.Anthropic") as mock_class:
            mock_client = MagicMock()
            mock_client.messages.create.return_value = mock_anthropic_response
            mock_class.return_value = mock_client

            client = AnthropicClient()
            client.gerar_oracao(pedido)

        call_kwargs = mock_client.messages.create.call_args[1]
        assert call_kwargs["system"] == "Sistema de oração pastoral."


@pytest.mark.django_db
class TestAnthropicClientPedidoVazio:
    """Testes para pedido vazio."""

    def test_pedido_vazio_uses_marker(self, template_ativo, mock_anthropic_response):
        """Pedido vazio inclui marker no prompt."""
        plano = PlanFactory(complexidade=Complexidade.SIMPLES)
        pedido = PedidoFactory(
            nome="Maria",
            pedido_oracao="",
            plano=plano,
        )

        with patch("clama.prayer_generation.services.anthropic_client.anthropic.Anthropic") as mock_class:
            mock_client = MagicMock()
            mock_client.messages.create.return_value = mock_anthropic_response
            mock_class.return_value = mock_client

            client = AnthropicClient()
            client.gerar_oracao(pedido)

        call_kwargs = mock_client.messages.create.call_args[1]
        user_content = call_kwargs["messages"][0]["content"]
        assert "[pedido vazio]" in user_content


@pytest.mark.django_db
class TestAnthropicClientComVersiculo:
    """Testes para plano COM_VERSICULO."""

    def test_com_versiculo_uses_correct_instruction(
        self, template_ativo, mock_anthropic_response
    ):
        """Pedido COM_VERSICULO usa instrução correta."""
        plano = PlanFactory(complexidade=Complexidade.COM_VERSICULO)
        pedido = PedidoFactory(
            nome="Maria",
            pedido_oracao="Peço oração.",
            plano=plano,
        )

        with patch("clama.prayer_generation.services.anthropic_client.anthropic.Anthropic") as mock_class:
            mock_client = MagicMock()
            mock_client.messages.create.return_value = mock_anthropic_response
            mock_class.return_value = mock_client

            client = AnthropicClient()
            client.gerar_oracao(pedido)

        call_kwargs = mock_client.messages.create.call_args[1]
        user_content = call_kwargs["messages"][0]["content"]
        assert "Gere uma oração com versículo." in user_content


@pytest.mark.django_db
class TestAnthropicClientRetry:
    """Testes de retry do AnthropicClient."""

    def test_retry_on_529_then_success(self, pedido, template_ativo, mock_anthropic_response):
        """Erro 529 (overloaded) retenta e sucesso na segunda tentativa."""
        # Create a mock error that behaves like APIStatusError with status 529
        error_529 = MagicMock(spec=anthropic.APIStatusError)
        error_529.status_code = 529
        error_529.message = "Overloaded"

        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise error_529
            return mock_anthropic_response

        with patch("clama.prayer_generation.services.anthropic_client.anthropic.Anthropic") as mock_class:
            mock_client = MagicMock()
            mock_client.messages.create.side_effect = side_effect
            mock_class.return_value = mock_client

            with patch("clama.core.retry.time.sleep"):  # Skip actual sleep
                client = AnthropicClient()
                result = client.gerar_oracao(pedido)

        assert result == "Querida Maria, que Deus abençoe..."
        assert call_count == 2

    def test_retry_exhausted_raises_error(self, pedido, template_ativo):
        """Retries esgotados levantam o erro original."""
        # Create a mock error that behaves like APIStatusError with status 529
        error_529 = MagicMock(spec=anthropic.APIStatusError)
        error_529.status_code = 529
        error_529.message = "Overloaded"

        with patch("clama.prayer_generation.services.anthropic_client.anthropic.Anthropic") as mock_class:
            mock_client = MagicMock()
            mock_client.messages.create.side_effect = error_529
            mock_class.return_value = mock_client

            with patch("clama.core.retry.time.sleep"):  # Skip actual sleep
                client = AnthropicClient()

                # After 3 retries, should raise the mock error
                with pytest.raises(MagicMock):
                    client.gerar_oracao(pedido)

    def test_connection_error_retries(self, pedido, template_ativo, mock_anthropic_response):
        """APIConnectionError retenta."""
        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise anthropic.APIConnectionError(request=MagicMock())
            return mock_anthropic_response

        with patch("clama.prayer_generation.services.anthropic_client.anthropic.Anthropic") as mock_class:
            mock_client = MagicMock()
            mock_client.messages.create.side_effect = side_effect
            mock_class.return_value = mock_client

            with patch("clama.core.retry.time.sleep"):
                client = AnthropicClient()
                result = client.gerar_oracao(pedido)

        assert result == "Querida Maria, que Deus abençoe..."
        assert call_count == 2

    def test_timeout_error_retries(self, pedido, template_ativo, mock_anthropic_response):
        """APITimeoutError retenta."""
        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise anthropic.APITimeoutError(request=MagicMock())
            return mock_anthropic_response

        with patch("clama.prayer_generation.services.anthropic_client.anthropic.Anthropic") as mock_class:
            mock_client = MagicMock()
            mock_client.messages.create.side_effect = side_effect
            mock_class.return_value = mock_client

            with patch("clama.core.retry.time.sleep"):
                client = AnthropicClient()
                result = client.gerar_oracao(pedido)

        assert result == "Querida Maria, que Deus abençoe..."
        assert call_count == 2


@pytest.mark.django_db
class TestAnthropicClientNonRetriableErrors:
    """Testes para erros não retriáveis."""

    def test_400_error_raises_immediately(self, pedido, template_ativo):
        """Erro 400 não retenta e levanta PrayerGenerationError."""
        # Create a real-like APIStatusError subclass for proper isinstance check
        class MockAPIStatusError(anthropic.APIStatusError):
            def __init__(self, status_code, message):
                self.status_code = status_code
                self.message = message
                # Don't call super().__init__() to avoid signature issues

        error_400 = MockAPIStatusError(400, "Bad request")

        with patch("clama.prayer_generation.services.anthropic_client.anthropic.Anthropic") as mock_class:
            mock_client = MagicMock()
            mock_client.messages.create.side_effect = error_400
            mock_class.return_value = mock_client

            client = AnthropicClient()

            with pytest.raises(PrayerGenerationError):
                client.gerar_oracao(pedido)

            # Deve ter sido chamado apenas 1 vez (sem retry)
            assert mock_client.messages.create.call_count == 1
