"""
Provisionamento/vínculo de conta do doador na confirmação do pagamento.

Chamado dentro do `transaction.atomic()` do webhook Mercado Pago, após o
repasse. Idempotente e à prova de enumeração: o efeito externo é sempre
"pedido vinculado a uma conta" — nunca revela se a conta já existia.
"""

import logging
from typing import TYPE_CHECKING

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.db.models import Q

from clama.freemium.hashing import hash_email, normalizar_email
from clama.freemium.temp_password import (
    encriptar_senha_para_cache,
    gerar_senha_temporaria,
)

if TYPE_CHECKING:
    from clama.orders.models import Pedido
    from clama_backend.users.models import User

logger = logging.getLogger("clama.customers.account_provisioning")

# Cache onde a senha temporária (encriptada Fernet) do doador recém-criado
# fica disponível para a task de e-mail de boas-vindas. Keyed por user_id,
# TTL 24h para cobrir delays/retries do SMTP. Prefixo distinto do freemium
# (`freemium:temp_password:`) para não colidir com aquela task/leitura.
DOADOR_TEMP_PASSWORD_CACHE_PREFIX = "doador:temp_password:"
DOADOR_TEMP_PASSWORD_TTL_SECONDS = 24 * 60 * 60


def key_temp_password_doador(user_id) -> str:
    """Chave de cache da senha temporária do doador (keyed por user_id)."""
    return f"{DOADOR_TEMP_PASSWORD_CACHE_PREFIX}{user_id}"


def _buscar_user_existente(user_model, email: str, email_hash: str):
    """Busca User por e-mail (plain iexact OU hash determinístico)."""
    return user_model.objects.filter(
        Q(email__iexact=email) | Q(email_hash=email_hash)
    ).first()


def provisionar_ou_vincular_conta_doador(
    pedido: "Pedido",
) -> "tuple[User | None, bool]":
    """Idempotente: vincula/cria a conta do doador pelo e-mail do pedido; no-op se já houver user."""
    # Idempotência: pedido já vinculado a um user → nada a fazer. Cobre o
    # webhook reentrante (2ª entrega não cria 2ª conta nem 2º e-mail).
    if pedido.user_id is not None:
        logger.info(
            "Provisionamento de doador ignorado — pedido já vinculado",
            extra={
                "event": "doador_provisionamento_ja_vinculado",
                "pedido_id": str(pedido.id),
            },
        )
        return pedido.user, False

    email = normalizar_email(pedido.email or "")
    if not email:
        logger.info(
            "Provisionamento de doador sem e-mail — nada a fazer",
            extra={
                "event": "doador_provisionamento_sem_email",
                "pedido_id": str(pedido.id),
            },
        )
        return None, False

    dominio = email.rsplit("@", 1)[-1] if "@" in email else "?"
    email_hash_req = hash_email(email)
    user_model = get_user_model()

    user = _buscar_user_existente(user_model, email, email_hash_req)
    if user is not None:
        # Conta já existe → vincula silenciosamente, sem tocar na senha. O
        # recibo é o e-mail de oração normal (gerar_oracao_task); nada de
        # credenciais. Anti-enumeração: efeito externo idêntico ao caso novo.
        pedido.user = user
        pedido.save(update_fields=["user"])
        logger.info(
            "Doação vinculada a conta existente",
            extra={
                "event": "doador_vinculado_conta_existente",
                "pedido_id": str(pedido.id),
                "email_dominio": dominio,
                "email_hash": email_hash_req,
            },
        )
        return user, False

    # Conta não existe → cria com senha temporária + force_change_password.
    # O `create_user` roda num savepoint aninhado: se colidir por e-mail
    # duplicado (corrida), o IntegrityError rolla só o savepoint e a
    # transação envolvente do webhook continua utilizável para o re-lookup.
    senha_temp = gerar_senha_temporaria()
    try:
        with transaction.atomic():
            user = user_model.objects.create_user(
                email=email,
                password=senha_temp,
                nome_completo=(pedido.nome or ""),
                cpf_cnpj=pedido.cpf_cnpj,
                telefone=pedido.telefone,
                idade=pedido.idade,
                sexo=pedido.sexo,
                force_change_password=True,
            )
    except IntegrityError as exc:
        # Corrida: outra transação criou a conta com o mesmo e-mail entre o
        # lookup e o create. Re-busca e vincula — resultado externo idêntico
        # (sem oracle de enumeração).
        user = _buscar_user_existente(user_model, email, email_hash_req)
        if user is None:
            raise
        pedido.user = user
        pedido.save(update_fields=["user"])
        logger.info(
            "Doação vinculada a conta existente (corrida no create)",
            extra={
                "event": "doador_vinculado_corrida",
                "pedido_id": str(pedido.id),
                "email_dominio": dominio,
                "email_hash": email_hash_req,
                "error": str(exc),
            },
        )
        return user, False

    # Vincula o pedido antes de tocar no cache (durável primeiro; se o save
    # falhar, o cache não fica com senha órfã de um pedido sem vínculo).
    pedido.user = user
    pedido.save(update_fields=["user"])

    # Persiste a senha temp encriptada (Fernet) para a task de boas-vindas.
    # NUNCA logamos a senha em claro — só trafega criptografada pelo cache.
    senha_cifrada = encriptar_senha_para_cache(senha_temp)
    cache.set(
        key_temp_password_doador(user.id),
        senha_cifrada,
        timeout=DOADOR_TEMP_PASSWORD_TTL_SECONDS,
    )

    logger.info(
        "Conta de doador provisionada",
        extra={
            "event": "doador_conta_provisionada",
            "pedido_id": str(pedido.id),
            "user_id": str(user.id),
            "email_dominio": dominio,
            "email_hash": email_hash_req,
        },
    )
    return user, True
