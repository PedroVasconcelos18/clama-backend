"""
Testes para views admin de pedidos.
"""
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from clama.orders.models import PedidoStatus
from clama.orders.tests.factories import PedidoFactory

User = get_user_model()


@pytest.fixture(autouse=True)
def clear_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def admin_user(db):
    return User.objects.create_user(
        email="admin@clama.test",
        password="test-pass",
        is_clama_admin=True,
    )


@pytest.fixture
def api_client(admin_user):
    client = APIClient()
    client.force_authenticate(user=admin_user)
    return client


@pytest.mark.django_db
class TestAdminPedidoReenviar:
    """Testes para POST /api/admin/pedidos/{id}/reenviar/."""

    def test_regera_oracao_quando_sem_oracao_e_status_erro(self, api_client):
        """Pedido ERRO sem oração → dispara gerar_oracao_task e volta a PAGO."""
        pedido = PedidoFactory(
            status=PedidoStatus.ERRO,
            oracao_gerada="",
            last_error="credit_balance",
            retry_count=2,
        )

        url = reverse("admin_api:pedidos-reenviar", kwargs={"id": pedido.id})
        with patch(
            "clama.prayer_generation.tasks.gerar_oracao_task.delay"
        ) as mock_gerar:
            response = api_client.post(url)

        assert response.status_code == status.HTTP_200_OK
        pedido.refresh_from_db()
        assert pedido.status == PedidoStatus.PAGO
        assert pedido.retry_count == 0
        assert pedido.last_error == ""
        mock_gerar.assert_called_once_with(str(pedido.id))

    def test_regera_oracao_quando_sem_oracao_e_status_aguardando_reenvio(
        self, api_client
    ):
        """Pedido AGUARDANDO_REENVIO sem oração → também regera."""
        pedido = PedidoFactory(
            status=PedidoStatus.AGUARDANDO_REENVIO,
            oracao_gerada="",
        )

        url = reverse("admin_api:pedidos-reenviar", kwargs={"id": pedido.id})
        with patch(
            "clama.prayer_generation.tasks.gerar_oracao_task.delay"
        ) as mock_gerar:
            response = api_client.post(url)

        assert response.status_code == status.HTTP_200_OK
        pedido.refresh_from_db()
        assert pedido.status == PedidoStatus.PAGO
        mock_gerar.assert_called_once_with(str(pedido.id))

    def test_reenvia_email_quando_com_oracao(self, api_client):
        """Pedido com oração_gerada mantém comportamento atual: ORACAO_GERADA + envio."""
        pedido = PedidoFactory(
            status=PedidoStatus.ENVIADA,
            oracao_gerada="Oração já gerada.",
        )

        url = reverse("admin_api:pedidos-reenviar", kwargs={"id": pedido.id})
        with patch(
            "clama.notifications.tasks.enviar_oracao_task.delay"
        ) as mock_enviar, patch(
            "clama.prayer_generation.tasks.gerar_oracao_task.delay"
        ) as mock_gerar:
            response = api_client.post(url)

        assert response.status_code == status.HTTP_200_OK
        pedido.refresh_from_db()
        assert pedido.status == PedidoStatus.ORACAO_GERADA
        mock_enviar.assert_called_once_with(str(pedido.id))
        mock_gerar.assert_not_called()

    def test_pedido_pago_sem_oracao_retorna_400(self, api_client):
        """Pedido PAGO sem oração (não travado) não é regerado aqui — retorna 400."""
        pedido = PedidoFactory(
            status=PedidoStatus.PAGO,
            oracao_gerada="",
        )

        url = reverse("admin_api:pedidos-reenviar", kwargs={"id": pedido.id})
        response = api_client.post(url)

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_sem_autenticacao_retorna_401(self):
        """Requisição sem admin autenticado é bloqueada."""
        pedido = PedidoFactory(status=PedidoStatus.ERRO, oracao_gerada="")
        client = APIClient()
        url = reverse("admin_api:pedidos-reenviar", kwargs={"id": pedido.id})
        response = client.post(url)

        assert response.status_code in (
            status.HTTP_401_UNAUTHORIZED,
            status.HTTP_403_FORBIDDEN,
        )


@pytest.mark.django_db
class TestAdminPedidoMarcarGratuito:
    """Testes para POST /api/admin/pedidos/{id}/marcar-gratuito/."""

    def test_marca_gratuito_e_dispara_task(
        self, api_client, django_capture_on_commit_callbacks
    ):
        pedido = PedidoFactory(
            status=PedidoStatus.AGUARDANDO_PAGAMENTO,
            valor_centavos=2000,
            eh_gratuito=False,
        )
        url = reverse("admin_api:pedidos-marcar-gratuito", kwargs={"id": pedido.id})

        with patch(
            "clama.prayer_generation.tasks.gerar_oracao_task.delay"
        ) as mock_gerar:
            with django_capture_on_commit_callbacks(execute=True):
                response = api_client.post(url)

        assert response.status_code == status.HTTP_200_OK
        pedido.refresh_from_db()
        assert pedido.eh_gratuito is True
        assert pedido.valor_centavos == 0
        assert pedido.status == PedidoStatus.GERANDO_ORACAO
        mock_gerar.assert_called_once_with(str(pedido.id))

    def test_enviada_retorna_409(self, api_client):
        pedido = PedidoFactory(status=PedidoStatus.ENVIADA)
        url = reverse("admin_api:pedidos-marcar-gratuito", kwargs={"id": pedido.id})

        with patch(
            "clama.prayer_generation.tasks.gerar_oracao_task.delay"
        ) as mock_gerar:
            response = api_client.post(url)

        assert response.status_code == status.HTTP_409_CONFLICT
        mock_gerar.assert_not_called()

    def test_idempotente_nao_redispara(self, api_client):
        pedido = PedidoFactory(
            status=PedidoStatus.GERANDO_ORACAO,
            eh_gratuito=True,
            valor_centavos=0,
        )
        url = reverse("admin_api:pedidos-marcar-gratuito", kwargs={"id": pedido.id})

        with patch(
            "clama.prayer_generation.tasks.gerar_oracao_task.delay"
        ) as mock_gerar:
            response = api_client.post(url)

        assert response.status_code == status.HTTP_200_OK
        mock_gerar.assert_not_called()

    def test_pedido_inexistente_retorna_404(self, api_client):
        import uuid

        url = reverse(
            "admin_api:pedidos-marcar-gratuito", kwargs={"id": uuid.uuid4()}
        )
        response = api_client.post(url)
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_sem_auth_retorna_401(self):
        pedido = PedidoFactory()
        client = APIClient()
        url = reverse("admin_api:pedidos-marcar-gratuito", kwargs={"id": pedido.id})
        response = client.post(url)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_detail_expoe_eh_gratuito(self, api_client):
        pedido = PedidoFactory(eh_gratuito=True)
        url = reverse("admin_api:pedidos-detail", kwargs={"id": pedido.id})
        response = api_client.get(url)
        assert response.status_code == status.HTTP_200_OK
        assert response.data["eh_gratuito"] is True
