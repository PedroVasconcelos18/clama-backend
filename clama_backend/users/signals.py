"""
Signals do app users — mantém os hashes do User (email/cpf/telefone)
sincronizados com os campos plaintext correspondentes.

Os hashes alimentam o user-existence gate do fluxo freemium (Landing Page).
Como `cpf_cnpj` e `telefone` são `EncryptedCharField` (não dá pra filtrar
diretamente pelo cleartext), o gate consulta as colunas hash. Manter os
hashes em sync via signal evita que callers esqueçam de setar manualmente
(`User.objects.create_user(...)`, `user.save()`, admin edits).

`bulk_create` NÃO dispara `pre_save` signals — quem usa bulk em scripts de
backfill / migração precisa setar `email_hash`, `cpf_hash`, `telefone_hash`
explicitamente.
"""

from django.db.models.signals import pre_save
from django.dispatch import receiver

from clama.freemium.hashing import (
    hash_cpf_cnpj,
    hash_email,
    hash_telefone,
)

from .models import User


@receiver(pre_save, sender=User)
def atualiza_hashes_user(sender, instance: User, **kwargs):
    """
    Recalcula `email_hash`, `cpf_hash`, `telefone_hash` antes do save.

    Sempre recalcula a partir dos campos plaintext atuais. Isso é
    idempotente (re-save com mesmo valor mantém o hash) e é o único caminho
    que cobre `update_fields=[...]` corretamente — se o caller atualizar
    apenas `email`, o save() ainda vai recompute `email_hash` pra refletir.

    Para campos opcionais (`cpf_cnpj`, `telefone`), valor vazio/None resulta
    em hash da string vazia. Não usamos None pra preservar o índice (queries
    `cpf_hash=hash_cpf_cnpj("")` ainda batem em users sem CPF — protege
    contra bypass acidental do gate por valor vazio submetido).
    """
    instance.email_hash = hash_email(instance.email or "")
    instance.cpf_hash = hash_cpf_cnpj(instance.cpf_cnpj or "")
    instance.telefone_hash = hash_telefone(instance.telefone or "")
