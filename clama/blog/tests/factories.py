"""Factories para testes do app blog."""

import factory
from django.contrib.auth import get_user_model
from factory.django import DjangoModelFactory

from clama.blog.models import Comentario, Post, PostStatus, Reacao, ReacaoTipo


class BlogUserFactory(DjangoModelFactory):
    class Meta:
        model = get_user_model()
        django_get_or_create = ("email",)

    email = factory.Sequence(lambda n: f"autor-blog-{n}@clama.test")
    is_clama_admin = True


class BlogCustomerFactory(DjangoModelFactory):
    """Customer (não-admin) — Juliana persona."""

    class Meta:
        model = get_user_model()
        django_get_or_create = ("email",)

    email = factory.Sequence(lambda n: f"customer-blog-{n}@clama.test")
    is_clama_admin = False


class PostFactory(DjangoModelFactory):
    class Meta:
        model = Post

    slug = factory.Sequence(lambda n: f"post-teste-{n}")
    titulo = factory.Faker("sentence", nb_words=5, locale="pt_BR")
    conteudo_html = "<p>Conteúdo de teste</p>"
    conteudo_tiptap_json = factory.LazyFunction(lambda: {"type": "doc", "content": []})
    excerpt = factory.Faker("sentence", nb_words=10, locale="pt_BR")
    autor = factory.SubFactory(BlogUserFactory)
    status = PostStatus.RASCUNHO


class ComentarioFactory(DjangoModelFactory):
    class Meta:
        model = Comentario

    post = factory.SubFactory(PostFactory)
    customer = factory.SubFactory(BlogCustomerFactory)
    conteudo = factory.Faker("sentence", nb_words=15, locale="pt_BR")
    ip_address = "192.168.0.1"
    is_suspeito = False


class ReacaoFactory(DjangoModelFactory):
    class Meta:
        model = Reacao

    post = factory.SubFactory(PostFactory)
    customer = factory.SubFactory(BlogCustomerFactory)
    tipo = ReacaoTipo.LIKE
