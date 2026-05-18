from io import StringIO

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError

from clama.blog.models import Comentario, CustomerBanido, Reacao
from clama.blog.tests.factories import (
    BlogCustomerFactory,
    BlogUserFactory,
    ComentarioFactory,
    CustomerBanidoFactory,
    ReacaoFactory,
)

User = get_user_model()


def _call(email, **kwargs):
    out = StringIO()
    err = StringIO()
    call_command(
        "purgar_dados_blog_customer", email, stdout=out, stderr=err, **kwargs
    )
    return out.getvalue(), err.getvalue()


@pytest.mark.django_db
class TestPurgarDadosBlogCustomer:
    def test_apaga_comentarios_e_reacoes(self):
        customer = BlogCustomerFactory(email="juliana@clama.test")
        ComentarioFactory(customer=customer)
        ComentarioFactory(customer=customer)
        ReacaoFactory(customer=customer)
        # Outro customer pra garantir isolation
        outro = BlogCustomerFactory()
        ComentarioFactory(customer=outro)

        out, _ = _call("juliana@clama.test", yes=True)

        assert Comentario.objects.filter(customer=customer).count() == 0
        assert Reacao.objects.filter(customer=customer).count() == 0
        # Outro customer não foi tocado
        assert Comentario.objects.filter(customer=outro).count() == 1
        assert "Removidos: 2 comentarios, 1 reacoes" in out

    def test_dry_run_nao_apaga(self):
        customer = BlogCustomerFactory(email="juliana@clama.test")
        ComentarioFactory(customer=customer)
        ReacaoFactory(customer=customer)

        out, _ = _call("juliana@clama.test", dry_run=True)

        assert Comentario.objects.filter(customer=customer).count() == 1
        assert Reacao.objects.filter(customer=customer).count() == 1
        assert "DRY-RUN" in out
        assert "1 comentarios" in out
        assert "1 reacoes" in out

    def test_user_account_nao_deletado(self):
        customer = BlogCustomerFactory(email="juliana@clama.test")
        ComentarioFactory(customer=customer)
        _call("juliana@clama.test", yes=True)
        # User permanece (LGPD do blog não toca em conta)
        assert User.objects.filter(email="juliana@clama.test").exists()

    def test_pedido_nao_deletado(self):
        # Indireto: management command só toca em Comentario/Reacao explicitamente.
        # Verificamos que delete não acionou cascade pra outro app.
        customer = BlogCustomerFactory(email="juliana@clama.test")
        ComentarioFactory(customer=customer)
        _call("juliana@clama.test", yes=True)
        # User intacto significa Pedidos via FK PROTECT também intactos.
        assert User.objects.filter(email="juliana@clama.test").exists()

    def test_banimento_nao_deletado(self):
        customer = BlogCustomerFactory(email="juliana@clama.test")
        admin = BlogUserFactory()
        CustomerBanidoFactory(customer=customer, banido_por=admin)
        _call("juliana@clama.test", yes=True)
        # Banimento permanece pra auditoria
        assert CustomerBanido.objects.filter(customer=customer).exists()

    def test_customer_inexistente_raise(self):
        with pytest.raises(CommandError, match="nao encontrado"):
            _call("naoexiste@clama.test", yes=True)

    def test_case_insensitive_lookup(self):
        BlogCustomerFactory(email="JuLiAnA@clama.test")
        ComentarioFactory(customer=User.objects.get(email__iexact="juliana@clama.test"))
        out, _ = _call("juliana@clama.test", yes=True)
        assert "Removidos: 1 comentarios" in out

    def test_customer_sem_dados_no_blog(self):
        BlogCustomerFactory(email="quieto@clama.test")
        out, _ = _call("quieto@clama.test", yes=True)
        assert "Removidos: 0 comentarios, 0 reacoes" in out
