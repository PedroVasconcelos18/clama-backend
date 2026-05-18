"""Tests pra Story 4.10 — customer escolhe formato do nome no blog.

Cobre:
- Default = COMPACTO no User
- `_autor_nome_publico` honra preferência
- GET /api/customer/me/ retorna nome_format_blog
- PATCH /api/customer/me/ atualiza nome_format_blog
- Integration: serializers públicos refletem preferência por user
"""

from unittest.mock import MagicMock

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from clama.blog.models import PostStatus
from clama.blog.serializers import _autor_nome_publico
from clama.blog.tests.factories import (
    BlogCustomerFactory,
    BlogUserFactory,
    ComentarioFactory,
    PostFactory,
)
from clama_backend.users.models import NomeFormatBlog


class TestAutorNomePublico:
    def test_user_none_retorna_pedro(self):
        assert _autor_nome_publico(None) == "Pedro"

    def test_user_sem_nome_completo_retorna_pedro(self):
        user = MagicMock()
        user.nome_completo = ""
        user.nome_format_blog = "completo"
        assert _autor_nome_publico(user) == "Pedro"

    def test_completo_retorna_nome_inteiro(self):
        user = MagicMock()
        user.nome_completo = "Juliana Silva"
        user.nome_format_blog = "completo"
        assert _autor_nome_publico(user) == "Juliana Silva"

    def test_compacto_retorna_primeiro_mais_inicial(self):
        user = MagicMock()
        user.nome_completo = "Juliana Silva"
        user.nome_format_blog = "compacto"
        assert _autor_nome_publico(user) == "Juliana S."

    def test_compacto_com_multiplos_sobrenomes_usa_ultimo(self):
        user = MagicMock()
        user.nome_completo = "Maria José Santos Oliveira"
        user.nome_format_blog = "compacto"
        assert _autor_nome_publico(user) == "Maria O."

    def test_compacto_sem_sobrenome_retorna_apenas_primeiro(self):
        user = MagicMock()
        user.nome_completo = "Juliana"
        user.nome_format_blog = "compacto"
        assert _autor_nome_publico(user) == "Juliana"

    def test_sem_atributo_nome_format_blog_assume_compacto(self):
        # Defesa: se algum caminho carrega user sem o atributo (ex.: mock
        # incompleto), fallback é compacto (privacy-friendly).
        class MinimalUser:
            nome_completo = "Juliana Silva"

        assert _autor_nome_publico(MinimalUser()) == "Juliana S."


@pytest.mark.django_db
class TestUserModelDefault:
    def test_default_is_compacto(self):
        u = BlogCustomerFactory()
        assert u.nome_format_blog == NomeFormatBlog.COMPACTO

    def test_factory_pode_passar_completo(self):
        u = BlogCustomerFactory(nome_format_blog=NomeFormatBlog.COMPLETO)
        assert u.nome_format_blog == NomeFormatBlog.COMPLETO


@pytest.mark.django_db
class TestCustomerMeEndpoint:
    URL = "/api/customer/me/"

    def test_get_inclui_nome_format_blog(self):
        user = BlogCustomerFactory(nome_completo="Juliana Silva")
        client = APIClient()
        client.force_authenticate(user=user)
        response = client.get(self.URL)
        assert response.status_code == 200
        assert response.json()["nome_format_blog"] == "compacto"

    def test_patch_atualiza_nome_format_blog(self):
        user = BlogCustomerFactory()
        client = APIClient()
        client.force_authenticate(user=user)
        response = client.patch(
            self.URL, {"nome_format_blog": "completo"}, format="json"
        )
        assert response.status_code == 200, response.content
        user.refresh_from_db()
        assert user.nome_format_blog == NomeFormatBlog.COMPLETO

    def test_patch_value_invalido_400(self):
        user = BlogCustomerFactory()
        client = APIClient()
        client.force_authenticate(user=user)
        response = client.patch(
            self.URL, {"nome_format_blog": "foo"}, format="json"
        )
        assert response.status_code == 400

    def test_patch_email_e_ignorado_readonly(self):
        user = BlogCustomerFactory(nome_completo="Juliana Silva")
        original_email = user.email
        client = APIClient()
        client.force_authenticate(user=user)
        response = client.patch(
            self.URL, {"email": "novo@clama.test"}, format="json"
        )
        assert response.status_code == 200
        user.refresh_from_db()
        assert user.email == original_email

    def test_patch_requer_auth(self):
        client = APIClient()
        response = client.patch(
            self.URL, {"nome_format_blog": "completo"}, format="json"
        )
        assert response.status_code in (401, 403)


@pytest.mark.django_db
class TestSerializerIntegration:
    def test_post_publico_reflete_preferencia_do_autor(self):
        admin = BlogUserFactory(
            nome_completo="Pedro Vasconcelos",
            nome_format_blog=NomeFormatBlog.COMPLETO,
        )
        post = PostFactory(
            slug="post-1",
            status=PostStatus.PUBLICADO,
            data_publicacao=timezone.now(),
            autor=admin,
        )
        client = APIClient()
        response = client.get(f"/api/blog/public/posts/{post.slug}/")
        assert response.status_code == 200
        assert response.json()["autor_nome"] == "Pedro Vasconcelos"

    def test_comments_publico_reflete_preferencia_do_customer(self):
        customer = BlogCustomerFactory(
            nome_completo="Juliana Silva",
            nome_format_blog=NomeFormatBlog.COMPACTO,
        )
        post = PostFactory(
            slug="post-2",
            status=PostStatus.PUBLICADO,
            data_publicacao=timezone.now(),
        )
        ComentarioFactory(post=post, customer=customer, conteudo="texto pastoral")
        client = APIClient()
        response = client.get(f"/api/blog/posts/{post.slug}/comments/")
        body = response.json()
        assert body["results"][0]["customer_nome"] == "Juliana S."
