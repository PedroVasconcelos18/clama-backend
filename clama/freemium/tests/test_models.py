"""
Testes do modelo FreemiumBlacklist e dos helpers de hashing.

Pós-renegociação 2026-05-08: testes específicos do `telefone_hash` foram
removidos (campo dropado). Os helpers `hash_telefone` / `normalizar_telefone`
permanecem em `hashing.py` por enquanto — podem ser usados em fluxos
futuros — mas a blacklist passou a ser somente (CPF, e-mail).
"""

import pytest
from django.db import IntegrityError

from clama.freemium.hashing import (
    hash_cpf_cnpj,
    hash_email,
    hash_telefone,
    normalizar_cpf_cnpj,
    normalizar_email,
    normalizar_telefone,
)
from clama.freemium.models import FreemiumBlacklist


class TestHashing:
    def test_normalizar_cpf_remove_mascara(self):
        assert normalizar_cpf_cnpj("123.456.789-09") == "12345678909"

    def test_normalizar_cpf_handles_none(self):
        assert normalizar_cpf_cnpj("") == ""

    def test_normalizar_email_lowercase_strip(self):
        assert normalizar_email("  Foo@Bar.COM ") == "foo@bar.com"

    def test_normalizar_email_gmail_remove_dots(self):
        """P-V11 wave 2: dots no localpart de Gmail são ignorados."""
        assert normalizar_email("a.l.i.c.e@gmail.com") == "alice@gmail.com"

    def test_normalizar_email_gmail_remove_plus_alias(self):
        """P-V11 wave 2: alias `+` em Gmail é canonicalizado fora."""
        assert normalizar_email("alice+spam@gmail.com") == "alice@gmail.com"

    def test_normalizar_email_gmail_combina_dots_e_plus(self):
        assert (
            normalizar_email("Al.i.ce+algo@GMAIL.com")
            == "alice@gmail.com"
        )

    def test_normalizar_email_googlemail_canonicaliza_para_gmail(self):
        """googlemail.com é alias do gmail.com (UK/DE)."""
        assert (
            normalizar_email("alice+x@googlemail.com")
            == "alice@gmail.com"
        )

    def test_normalizar_email_dominios_nao_gmail_preservam_dots(self):
        """Outlook / domínios corporativos tratam dots como significativos."""
        assert (
            normalizar_email("a.l.i.c.e@outlook.com")
            == "a.l.i.c.e@outlook.com"
        )

    def test_hash_email_gmail_aliases_colidem(self):
        """P-V11: aliases Gmail compartilham o mesmo hash de blacklist."""
        h1 = hash_email("alice@gmail.com")
        h2 = hash_email("a.l.i.c.e+spam@gmail.com")
        h3 = hash_email("alice+x@googlemail.com")
        assert h1 == h2 == h3

    def test_normalizar_telefone_so_digitos(self):
        assert normalizar_telefone("+55 (11) 99999-8888") == "5511999998888"

    def test_hash_cpf_e_deterministico(self):
        h1 = hash_cpf_cnpj("123.456.789-09")
        h2 = hash_cpf_cnpj("12345678909")
        assert h1 == h2
        assert len(h1) == 64  # SHA-256 hex

    def test_hash_email_case_insensitive(self):
        assert hash_email("Foo@Bar.com") == hash_email("foo@bar.com")

    def test_hash_telefone_ignora_mascara(self):
        assert hash_telefone("+55 11 99999-8888") == hash_telefone("5511999998888")

    def test_hashes_diferentes_para_inputs_diferentes(self):
        assert hash_cpf_cnpj("12345678909") != hash_cpf_cnpj("11144477735")


@pytest.mark.django_db
class TestFreemiumBlacklistModel:
    def test_pode_criar_entrada(self):
        entry = FreemiumBlacklist.objects.create(
            cpf_hash="a" * 64,
            email_hash="b" * 64,
        )
        assert entry.id is not None
        assert "FreemiumBlacklist" in str(entry)

    def test_cpf_hash_e_unico(self):
        FreemiumBlacklist.objects.create(
            cpf_hash="a" * 64,
            email_hash="b" * 64,
        )
        with pytest.raises(IntegrityError):
            FreemiumBlacklist.objects.create(
                cpf_hash="a" * 64,
                email_hash="d" * 64,
            )

    def test_email_hash_e_unico(self):
        FreemiumBlacklist.objects.create(
            cpf_hash="a" * 64,
            email_hash="b" * 64,
        )
        with pytest.raises(IntegrityError):
            FreemiumBlacklist.objects.create(
                cpf_hash="d" * 64,
                email_hash="b" * 64,
            )
