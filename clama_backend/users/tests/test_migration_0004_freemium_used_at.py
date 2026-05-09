"""
Testes da data migration `users/0004_freemium_used_at.py` (G2.a, AC6).

Cobre o backfill: Users com Pedidos `eh_gratuito=True` ganham
`freemium_used_at = min(Pedido.created_at)` desses pedidos. Users sem
pedido grátis (ou só com pedidos pagos) permanecem com NULL.

Estratégia (P-15): o backfill já está extraído como função top-level
`backfill_freemium_used_at(apps, schema_editor)` na própria migration.
Testamos diretamente passando um shim do `apps` que devolve o model
"corrente" via `get_model`. Isso é equivalente a `MigrationExecutor` mas
mais barato (não rebobina o schema), que seria pesado por conta dos
encrypted fields no `Pedido`.

O reverse também é coberto.
"""

import importlib
from datetime import timedelta

import pytest
from django.apps import apps as django_apps
from django.contrib.auth import get_user_model
from django.utils import timezone

from clama.orders.models import CanalEntrega, Pedido, PedidoStatus
from clama.plans.tests.factories import PlanFactory

User = get_user_model()


# Migrations com prefixo numérico ("0004_...") não podem ser carregadas via
# `import x.y.0004_z`; usamos `importlib.import_module` com o nome
# qualificado em string.
MIGRATION_MODULE_NAME = (
    "clama_backend.users.migrations.0004_freemium_used_at"
)


@pytest.fixture
def migration():
    """Carrega o módulo da migration uma vez."""
    return importlib.import_module(MIGRATION_MODULE_NAME)


@pytest.fixture
def fake_apps():
    """
    Shim que imita `apps` recebido em data migrations: oferece
    `get_model('app', 'Model')` resolvendo via app registry corrente do
    Django. Coerente com o subset que o backfill consome.
    """

    class _FakeApps:
        def get_model(self, app_label, model_name):
            return django_apps.get_model(app_label, model_name)

    return _FakeApps()


@pytest.fixture
def plano(db):
    return PlanFactory(ativo=True, valor_centavos=2000)


def _criar_pedido(plano, *, user, eh_gratuito, created_at=None):
    """Cria Pedido e força `created_at` (auto_now_add) via update."""
    pedido = Pedido.objects.create(
        plano=plano,
        valor_centavos=2000 if not eh_gratuito else 0,
        canal_entrega=CanalEntrega.EMAIL,
        status=PedidoStatus.ENVIADA,
        nome="Teste",
        email="t@example.com",
        cpf_cnpj="11144477735",
        user=user,
        eh_gratuito=eh_gratuito,
    )
    if created_at is not None:
        Pedido.objects.filter(pk=pedido.pk).update(created_at=created_at)
        pedido.refresh_from_db()
    return pedido


@pytest.mark.django_db
class TestBackfillFreemiumUsedAt:
    def test_user_com_um_pedido_gratuito_recebe_created_at(
        self, plano, migration, fake_apps
    ):
        ts = timezone.now() - timedelta(hours=2)
        user = User.objects.create_user(
            email="freemium@example.com",
            password="SenhaForte!#999",
        )
        # Garante estado inicial coerente (caso o setup do db já tenha
        # rodado a migration normalmente, a row já está com NULL).
        User.objects.filter(pk=user.pk).update(freemium_used_at=None)
        _criar_pedido(plano, user=user, eh_gratuito=True, created_at=ts)

        migration.backfill_freemium_used_at(fake_apps, schema_editor=None)

        user.refresh_from_db()
        assert user.freemium_used_at is not None
        # Permite drift de microssegundos por causa de timezone serialization.
        assert abs((user.freemium_used_at - ts).total_seconds()) < 1

    def test_user_com_multiplos_gratuitos_pega_o_minimo(
        self, plano, migration, fake_apps
    ):
        ts_antigo = timezone.now() - timedelta(days=10)
        ts_novo = timezone.now() - timedelta(hours=1)
        user = User.objects.create_user(
            email="multiplos@example.com",
            password="SenhaForte!#999",
        )
        User.objects.filter(pk=user.pk).update(freemium_used_at=None)
        _criar_pedido(plano, user=user, eh_gratuito=True, created_at=ts_novo)
        _criar_pedido(plano, user=user, eh_gratuito=True, created_at=ts_antigo)

        migration.backfill_freemium_used_at(fake_apps, schema_editor=None)

        user.refresh_from_db()
        assert user.freemium_used_at is not None
        # Pega o mais antigo dos dois.
        assert abs((user.freemium_used_at - ts_antigo).total_seconds()) < 1

    def test_user_sem_pedido_gratuito_permanece_null(
        self, plano, migration, fake_apps
    ):
        user = User.objects.create_user(
            email="sopagamento@example.com",
            password="SenhaForte!#999",
        )
        User.objects.filter(pk=user.pk).update(freemium_used_at=None)
        # Apenas pedido pago.
        _criar_pedido(plano, user=user, eh_gratuito=False)

        migration.backfill_freemium_used_at(fake_apps, schema_editor=None)

        user.refresh_from_db()
        assert user.freemium_used_at is None

    def test_user_sem_pedidos_permanece_null(self, migration, fake_apps):
        user = User.objects.create_user(
            email="sempedidos@example.com",
            password="SenhaForte!#999",
        )
        User.objects.filter(pk=user.pk).update(freemium_used_at=None)

        migration.backfill_freemium_used_at(fake_apps, schema_editor=None)

        user.refresh_from_db()
        assert user.freemium_used_at is None

    def test_reverse_zera_o_campo(self, plano, migration, fake_apps):
        ts = timezone.now() - timedelta(hours=5)
        user = User.objects.create_user(
            email="reverse@example.com",
            password="SenhaForte!#999",
        )
        _criar_pedido(plano, user=user, eh_gratuito=True, created_at=ts)
        migration.backfill_freemium_used_at(fake_apps, schema_editor=None)
        user.refresh_from_db()
        assert user.freemium_used_at is not None

        migration.reverse_freemium_used_at(fake_apps, schema_editor=None)
        user.refresh_from_db()
        assert user.freemium_used_at is None
