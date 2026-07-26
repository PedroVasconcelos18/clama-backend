"""
Testes do serviço `provisionar_ou_vincular_conta_doador`.

Cobre a I/O Matrix do provisionamento: e-mail novo (cria conta), e-mail
existente (vincula sem mexer na senha), pedido já vinculado (no-op) e a
corrida de e-mail duplicado (IntegrityError → vincula existente).

⚠️ Requerem DB/app-registry — rodam no ambiente provisionado.
"""
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import IntegrityError

from clama.customers.services.account_provisioning import (
    key_temp_password_doador,
    provisionar_ou_vincular_conta_doador,
)
from clama.freemium.temp_password import desencriptar_senha_do_cache
from clama.orders.tests.factories import PedidoFactory
from clama_backend.users.models import UserManager


@pytest.fixture(autouse=True)
def _clear_cache_around_each_test():
    cache.clear()
    yield
    cache.clear()


@pytest.mark.django_db
def test_email_novo_cria_conta_com_senha_temp_e_vincula_pedido():
    pedido = PedidoFactory(user=None, email="doador.novo@exemplo.com")

    user, criada = provisionar_ou_vincular_conta_doador(pedido)

    assert criada is True
    assert user is not None
    assert user.email == "doador.novo@exemplo.com"
    assert user.force_change_password is True
    assert user.nome_completo == pedido.nome

    pedido.refresh_from_db()
    assert pedido.user_id == user.id

    # Senha temporária no cache, encriptada e decriptável (14 chars).
    cached = cache.get(key_temp_password_doador(user.id))
    assert cached
    senha = desencriptar_senha_do_cache(cached)
    assert len(senha) == 14


@pytest.mark.django_db
def test_email_existente_vincula_sem_mexer_senha():
    user_model = get_user_model()
    existente = user_model.objects.create_user(
        email="existente@exemplo.com", password="SenhaOriginal123"
    )
    senha_hash_antes = existente.password

    pedido = PedidoFactory(user=None, email="existente@exemplo.com")

    user, criada = provisionar_ou_vincular_conta_doador(pedido)

    assert criada is False
    assert user.id == existente.id

    # Senha intacta — não geramos/aplicamos senha nova em conta existente.
    existente.refresh_from_db()
    assert existente.password == senha_hash_antes

    pedido.refresh_from_db()
    assert pedido.user_id == existente.id

    # Sem senha no cache — nenhuma credencial a enviar (anti-enumeração).
    assert cache.get(key_temp_password_doador(existente.id)) is None


@pytest.mark.django_db
def test_email_existente_por_hash_gmail_canonical_vincula():
    # Gmail canonicaliza dots/alias — o lookup por email_hash deve casar
    # mesmo quando o e-mail do pedido tem forma diferente do cadastrado.
    user_model = get_user_model()
    existente = user_model.objects.create_user(
        email="joao.silva@gmail.com", password="x"
    )

    pedido = PedidoFactory(user=None, email="j.o.a.o.silva+doacao@gmail.com")

    user, criada = provisionar_ou_vincular_conta_doador(pedido)

    assert criada is False
    assert user.id == existente.id
    pedido.refresh_from_db()
    assert pedido.user_id == existente.id


@pytest.mark.django_db
def test_pedido_ja_vinculado_e_no_op():
    user_model = get_user_model()
    existente = user_model.objects.create_user(email="ja@exemplo.com", password="x")
    pedido = PedidoFactory(user=existente, email="qualquer@exemplo.com")

    with patch.object(UserManager, "create_user") as mock_create:
        user, criada = provisionar_ou_vincular_conta_doador(pedido)

    assert criada is False
    assert user.id == existente.id
    mock_create.assert_not_called()


@pytest.mark.django_db
def test_pedido_sem_email_e_no_op():
    pedido = PedidoFactory(user=None, email="")

    with patch.object(UserManager, "create_user") as mock_create:
        user, criada = provisionar_ou_vincular_conta_doador(pedido)

    assert criada is False
    assert user is None
    mock_create.assert_not_called()


@pytest.mark.django_db
def test_corrida_integrityerror_vincula_conta_existente():
    user_model = get_user_model()
    # Conta "criada por outra transação" entre o lookup e o create.
    concorrente = user_model.objects.create_user(
        email="corrida@exemplo.com", password="x"
    )
    pedido = PedidoFactory(user=None, email="corrida@exemplo.com")

    # Força o caminho de corrida: lookup inicial não acha (None), create_user
    # levanta IntegrityError (e-mail duplicado), re-lookup acha a conta.
    with patch(
        "clama.customers.services.account_provisioning._buscar_user_existente",
        side_effect=[None, concorrente],
    ):
        with patch.object(
            UserManager, "create_user", side_effect=IntegrityError("duplicate key")
        ):
            user, criada = provisionar_ou_vincular_conta_doador(pedido)

    assert criada is False
    assert user.id == concorrente.id

    pedido.refresh_from_db()
    assert pedido.user_id == concorrente.id

    # Corrida não deixa credencial órfã no cache.
    assert cache.get(key_temp_password_doador(concorrente.id)) is None
