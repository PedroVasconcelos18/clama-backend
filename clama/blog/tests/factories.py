"""Factories para testes do app blog."""

import factory
from django.contrib.auth import get_user_model
from factory.django import DjangoModelFactory

from clama.blog.models import Post, PostStatus


class BlogUserFactory(DjangoModelFactory):
    class Meta:
        model = get_user_model()
        django_get_or_create = ("email",)

    email = factory.Sequence(lambda n: f"autor-blog-{n}@clama.test")
    is_clama_admin = True


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
