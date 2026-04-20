"""
Testes para as Celery tasks de geração de oração.
"""
from unittest.mock import patch

import pytest

from clama.orders.models import PedidoStatus
from clama.orders.tests.factories import PedidoFactory
from clama.prayer_generation.exceptions import InsufficientCreditsError
from clama.prayer_generation.tasks import gerar_oracao_task


@pytest.mark.django_db
class TestGerarOracaoTaskInsufficientCredits:
    """Testes para tratamento de InsufficientCreditsError em gerar_oracao_task."""

    def test_credit_balance_marca_erro_sem_reagendar(self):
        """Créditos insuficientes → status=ERRO, last_error=credit_balance, sem mock."""
        pedido = PedidoFactory(status=PedidoStatus.PAGO)

        with patch(
            "clama.prayer_generation.tasks.AnthropicClient"
        ) as mock_client_cls, patch(
            "clama.prayer_generation.tasks.gerar_oracao_task.apply_async"
        ) as mock_apply_async, patch(
            "clama.prayer_generation.tasks.sentry_sdk.capture_message"
        ) as mock_capture:
            mock_client_cls.return_value.gerar_oracao.side_effect = (
                InsufficientCreditsError(message="credit balance too low")
            )

            gerar_oracao_task(str(pedido.id))

        pedido.refresh_from_db()
        assert pedido.status == PedidoStatus.ERRO
        assert pedido.last_error == "credit_balance"
        assert pedido.oracao_gerada == ""
        # Não agenda retry nem nova execução
        mock_apply_async.assert_not_called()
        # Avisa Sentry para visibilidade operacional
        mock_capture.assert_called_once()

    def test_credit_balance_nao_chama_enviar(self):
        """Créditos insuficientes → enviar_oracao_task NÃO é enfileirada."""
        pedido = PedidoFactory(status=PedidoStatus.PAGO)

        with patch(
            "clama.prayer_generation.tasks.AnthropicClient"
        ) as mock_client_cls, patch(
            "clama.notifications.tasks.enviar_oracao_task.delay"
        ) as mock_enviar:
            mock_client_cls.return_value.gerar_oracao.side_effect = (
                InsufficientCreditsError(message="credit balance too low")
            )

            gerar_oracao_task(str(pedido.id))

        mock_enviar.assert_not_called()
