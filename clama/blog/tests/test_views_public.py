import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from clama.blog.models import PostStatus
from clama.blog.tests.factories import (
    BlogUserFactory,
    ComentarioFactory,
    PostFactory,
    ReacaoFactory,
)

LIST_URL = "/api/blog/public/posts/"


def _detail_url(slug):
    return f"{LIST_URL}{slug}/"


def _make_publicado(**kwargs):
    return PostFactory(
        status=PostStatus.PUBLICADO,
        data_publicacao=timezone.now(),
        **kwargs,
    )


@pytest.mark.django_db
class TestPublicListEndpoint:
    def test_anonymous_can_list(self):
        _make_publicado(slug="post-1")
        client = APIClient()
        response = client.get(LIST_URL)
        assert response.status_code == 200

    def test_only_publicados_appear(self):
        PostFactory(slug="rascunho-1", status=PostStatus.RASCUNHO)
        _make_publicado(slug="publicado-1")
        client = APIClient()
        response = client.get(LIST_URL)
        slugs = {p["slug"] for p in response.json()["results"]}
        assert "publicado-1" in slugs
        assert "rascunho-1" not in slugs

    def test_pagination_default_12(self):
        for i in range(13):
            _make_publicado(slug=f"post-{i}")
        client = APIClient()
        response = client.get(LIST_URL)
        body = response.json()
        assert body["count"] == 13
        assert len(body["results"]) == 12
        assert body["next"] is not None

    def test_list_omits_conteudo_html(self):
        _make_publicado(slug="post-1")
        client = APIClient()
        response = client.get(LIST_URL)
        item = response.json()["results"][0]
        assert "conteudo_html" not in item
        assert "conteudo_tiptap_json" not in item
        assert "autor" not in item  # ID/email do autor NÃO exposto
        assert "autor_nome" in item

    def test_list_includes_counts(self):
        post = _make_publicado(slug="post-1")
        ReacaoFactory(post=post)
        ReacaoFactory(post=post)
        ComentarioFactory(post=post)
        client = APIClient()
        response = client.get(LIST_URL)
        item = response.json()["results"][0]
        assert item["like_count"] == 2
        assert item["comment_count"] == 1


@pytest.mark.django_db
class TestPublicRetrieveEndpoint:
    def test_retrieve_publicado_by_slug(self):
        _make_publicado(slug="meu-post")
        client = APIClient()
        response = client.get(_detail_url("meu-post"))
        assert response.status_code == 200
        body = response.json()
        assert body["slug"] == "meu-post"
        assert "conteudo_html" in body
        assert "autor_nome" in body
        assert "autor" not in body  # ID interno NÃO exposto

    def test_retrieve_rascunho_returns_404(self):
        PostFactory(slug="rascunho-1", status=PostStatus.RASCUNHO)
        client = APIClient()
        response = client.get(_detail_url("rascunho-1"))
        assert response.status_code == 404

    def test_retrieve_unknown_slug_404(self):
        client = APIClient()
        response = client.get(_detail_url("nao-existe"))
        assert response.status_code == 404


@pytest.mark.django_db
class TestPublicReadOnlyEndpoints:
    def test_post_returns_405(self):
        client = APIClient()
        response = client.post(LIST_URL, {"slug": "x"}, format="json")
        assert response.status_code == 405

    def test_put_returns_405(self):
        post = _make_publicado(slug="post-1")
        client = APIClient()
        response = client.put(
            _detail_url(post.slug), {"titulo": "x"}, format="json"
        )
        assert response.status_code == 405

    def test_delete_returns_405(self):
        post = _make_publicado(slug="post-1")
        client = APIClient()
        response = client.delete(_detail_url(post.slug))
        assert response.status_code == 405


@pytest.mark.django_db
class TestPublicCacheHeader:
    def test_get_list_sets_cache_control(self):
        _make_publicado(slug="post-1")
        client = APIClient()
        response = client.get(LIST_URL)
        assert "public" in response.get("Cache-Control", "")
        assert "max-age=300" in response.get("Cache-Control", "")

    def test_get_detail_sets_cache_control(self):
        _make_publicado(slug="post-1")
        client = APIClient()
        response = client.get(_detail_url("post-1"))
        assert "max-age=300" in response.get("Cache-Control", "")


@pytest.mark.django_db
class TestAutorNomeFallback:
    def test_fallback_to_pedro_when_no_nome_completo(self):
        autor = BlogUserFactory(email="autor@clama.test", nome_completo="")
        _make_publicado(slug="post-1", autor=autor)
        client = APIClient()
        response = client.get(_detail_url("post-1"))
        assert response.json()["autor_nome"] == "Pedro"

    def test_uses_nome_completo_when_set(self):
        # Após Story 4.10, default `nome_format_blog="compacto"`. Para obter
        # o nome completo na resposta, autor precisa ter pref COMPLETO.
        autor = BlogUserFactory(
            email="pedro@clama.me",
            nome_completo="Pedro Pastor",
            nome_format_blog="completo",
        )
        _make_publicado(slug="post-2", autor=autor)
        client = APIClient()
        response = client.get(_detail_url("post-2"))
        assert response.json()["autor_nome"] == "Pedro Pastor"
