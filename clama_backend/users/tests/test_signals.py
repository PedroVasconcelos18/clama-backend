"""
Testes do `pre_save` signal que mantém os hashes do User sincronizados com
os campos plaintext (email/cpf_cnpj/telefone).
"""

import pytest
from django.contrib.auth import get_user_model

from clama.freemium.hashing import (
    hash_cpf_cnpj,
    hash_email,
    hash_telefone,
)

User = get_user_model()


@pytest.mark.django_db
class TestUserHashSignal:
    def test_create_user_seta_email_hash(self):
        user = User.objects.create_user(
            email="alice@example.com",
            password="senha-temp-12345",
        )
        assert user.email_hash == hash_email("alice@example.com")

    def test_create_user_seta_cpf_hash_quando_informado(self):
        user = User.objects.create_user(
            email="bob@example.com",
            password="senha-temp-12345",
            cpf_cnpj="12345678901",
        )
        assert user.cpf_hash == hash_cpf_cnpj("12345678901")

    def test_create_user_seta_telefone_hash_quando_informado(self):
        user = User.objects.create_user(
            email="carol@example.com",
            password="senha-temp-12345",
            telefone="+5511999998888",
        )
        assert user.telefone_hash == hash_telefone("+5511999998888")

    def test_user_sem_cpf_telefone_recebe_hash_de_string_vazia(self):
        """Users legacy/admin sem CPF/telefone — hash da string vazia."""
        user = User.objects.create_user(
            email="admin@example.com",
            password="senha-temp-12345",
        )
        assert user.cpf_hash == hash_cpf_cnpj("")
        assert user.telefone_hash == hash_telefone("")

    def test_save_recalcula_hash_quando_email_muda(self):
        user = User.objects.create_user(
            email="orig@example.com",
            password="senha-temp-12345",
        )
        user.email = "novo@example.com"
        user.save()
        assert user.email_hash == hash_email("novo@example.com")

    def test_update_fields_email_recalcula_email_hash(self):
        """`save(update_fields=["email"])` ainda dispara signal."""
        user = User.objects.create_user(
            email="orig@example.com",
            password="senha-temp-12345",
        )
        user.email = "novo@example.com"
        user.save(update_fields=["email", "email_hash"])
        # Recarrega do DB pra confirmar que o hash foi persistido.
        user.refresh_from_db()
        assert user.email_hash == hash_email("novo@example.com")

    def test_save_recalcula_hash_quando_cpf_muda(self):
        user = User.objects.create_user(
            email="dee@example.com",
            password="senha-temp-12345",
            cpf_cnpj="12345678901",
        )
        user.cpf_cnpj = "98765432100"
        user.save()
        assert user.cpf_hash == hash_cpf_cnpj("98765432100")

    def test_email_hash_canonicaliza_gmail_alias(self):
        """
        `alice.test+1@gmail.com` deve produzir o MESMO hash que
        `alicetest@gmail.com` (canonicalização Gmail). Isso é o que faz o
        gate do user-existence pegar o alias.
        """
        user = User.objects.create_user(
            email="alicetest@gmail.com",
            password="senha-temp-12345",
        )
        assert user.email_hash == hash_email("alice.test+1@gmail.com")
