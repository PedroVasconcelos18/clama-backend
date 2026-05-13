import pytest
from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APIClient

from clama.blog.models import PostStatus, Reacao, ReacaoTipo
from clama.blog.tests.factories import (
    BlogCustomerFactory,
    ComentarioFactory,
    PostFactory,
)


def _like_url(slug):
    return f"/api/blog/posts/{slug}/like/"


def _comments_url(slug):
    return f"/api/blog/posts/{slug}/comments/"


def _make_publicado(**kwargs):
    return PostFactory(
        status=PostStatus.PUBLICADO,
        data_publicacao=timezone.now(),
        **kwargs,
    )


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.mark.django_db
class TestReacaoToggle:
    def test_anonymous_cannot_toggle(self):
        _make_publicado(slug="post-1")
        client = APIClient()
        response = client.post(_like_url("post-1"))
        assert response.status_code in (401, 403)

    def test_first_post_creates_like(self):
        post = _make_publicado(slug="post-1")
        customer = BlogCustomerFactory()
        client = APIClient()
        client.force_authenticate(user=customer)
        response = client.post(_like_url("post-1"))
        assert response.status_code == 200, response.content
        body = response.json()
        assert body["liked"] is True
        assert body["like_count"] == 1
        assert Reacao.objects.filter(
            post=post, customer=customer, tipo=ReacaoTipo.LIKE
        ).exists()

    def test_second_post_removes_like(self):
        post = _make_publicado(slug="post-1")
        customer = BlogCustomerFactory()
        client = APIClient()
        client.force_authenticate(user=customer)
        # 1º
        r1 = client.post(_like_url("post-1"))
        assert r1.json()["liked"] is True
        # 2º (toggle off)
        r2 = client.post(_like_url("post-1"))
        assert r2.status_code == 200
        body = r2.json()
        assert body["liked"] is False
        assert body["like_count"] == 0
        assert not Reacao.objects.filter(post=post, customer=customer).exists()

    def test_third_post_creates_again(self):
        post = _make_publicado(slug="post-1")
        customer = BlogCustomerFactory()
        client = APIClient()
        client.force_authenticate(user=customer)
        client.post(_like_url("post-1"))
        client.post(_like_url("post-1"))
        r3 = client.post(_like_url("post-1"))
        assert r3.json()["liked"] is True
        assert r3.json()["like_count"] == 1

    def test_like_count_reflects_multiple_customers(self):
        _make_publicado(slug="post-1")
        c1 = BlogCustomerFactory()
        c2 = BlogCustomerFactory()
        for c in (c1, c2):
            client = APIClient()
            client.force_authenticate(user=c)
            client.post(_like_url("post-1"))
        # Último response reflete 2 likes
        client = APIClient()
        c3 = BlogCustomerFactory()
        client.force_authenticate(user=c3)
        r = client.post(_like_url("post-1"))
        assert r.json()["like_count"] == 3

    def test_rascunho_returns_404(self):
        PostFactory(slug="rascunho-1", status=PostStatus.RASCUNHO)
        customer = BlogCustomerFactory()
        client = APIClient()
        client.force_authenticate(user=customer)
        response = client.post(_like_url("rascunho-1"))
        assert response.status_code == 404

    def test_inexistent_returns_404(self):
        customer = BlogCustomerFactory()
        client = APIClient()
        client.force_authenticate(user=customer)
        response = client.post(_like_url("nao-existe"))
        assert response.status_code == 404

    def test_rate_limit_30_per_minute(self):
        _make_publicado(slug="post-1")
        customer = BlogCustomerFactory()
        client = APIClient()
        client.force_authenticate(user=customer)
        # 30 toggles OK (cada um alternando like/unlike) — então 31º deve ser 429
        for i in range(30):
            r = client.post(_like_url("post-1"))
            assert r.status_code == 200, (i, r.content)
        r31 = client.post(_like_url("post-1"))
        assert r31.status_code == 429
        assert r31.json()["code"] == "rate_limit_exceeded"

    def test_get_method_not_allowed(self):
        _make_publicado(slug="post-1")
        customer = BlogCustomerFactory()
        client = APIClient()
        client.force_authenticate(user=customer)
        response = client.get(_like_url("post-1"))
        assert response.status_code == 405


@pytest.mark.django_db
class TestCommentsNoindexHeader:
    def test_noindex_when_recent_comment_exists(self):
        post = _make_publicado(slug="post-1")
        ComentarioFactory(post=post)  # criado agora
        client = APIClient()
        response = client.get(_comments_url("post-1"))
        assert response.status_code == 200
        assert response.get("X-Robots-Tag") == "noindex"

    def test_no_noindex_when_no_comments(self):
        _make_publicado(slug="post-1")
        client = APIClient()
        response = client.get(_comments_url("post-1"))
        assert response.status_code == 200
        assert "X-Robots-Tag" not in response

    def test_no_noindex_when_only_old_comments(self):
        post = _make_publicado(slug="post-1")
        c = ComentarioFactory(post=post)
        # Backdate via update direto (bypass auto_now_add)
        old_dt = timezone.now() - timezone.timedelta(hours=25)
        type(c).objects.filter(id=c.id).update(created_at=old_dt)
        client = APIClient()
        response = client.get(_comments_url("post-1"))
        assert response.status_code == 200
        assert "X-Robots-Tag" not in response
