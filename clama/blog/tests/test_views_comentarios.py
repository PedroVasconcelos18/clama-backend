from unittest.mock import patch

import pytest
from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APIClient

from clama.blog.models import Comentario, PostStatus
from clama.blog.tests.factories import (
    BlogCustomerFactory,
    BlogUserFactory,
    ComentarioFactory,
    PostFactory,
)


def _list_url(slug):
    return f"/api/blog/posts/{slug}/comments/"


def _detail_url(comment_id):
    return f"/api/blog/comments/{comment_id}/"


def _make_publicado(**kwargs):
    return PostFactory(
        status=PostStatus.PUBLICADO,
        data_publicacao=timezone.now(),
        **kwargs,
    )


@pytest.fixture(autouse=True)
def _clear_cache():
    """Limpa cache antes/depois de cada teste pra isolar rate limit."""
    cache.clear()
    yield
    cache.clear()


@pytest.mark.django_db
class TestListComments:
    def test_anonymous_can_list(self):
        post = _make_publicado(slug="post-1")
        ComentarioFactory(post=post)
        client = APIClient()
        response = client.get(_list_url("post-1"))
        assert response.status_code == 200
        assert len(response.json()["results"]) == 1

    def test_list_only_returns_comments_of_correct_post(self):
        post1 = _make_publicado(slug="post-um")
        post2 = _make_publicado(slug="post-dois")
        ComentarioFactory(post=post1, conteudo="comentario um")
        ComentarioFactory(post=post2, conteudo="comentario dois")
        client = APIClient()
        response = client.get(_list_url("post-um"))
        assert response.status_code == 200
        conteudos = [c["conteudo"] for c in response.json()["results"]]
        assert "comentario um" in conteudos
        assert "comentario dois" not in conteudos

    def test_list_on_rascunho_post_returns_404(self):
        PostFactory(slug="rascunho-1", status=PostStatus.RASCUNHO)
        client = APIClient()
        response = client.get(_list_url("rascunho-1"))
        assert response.status_code == 404

    def test_list_sets_cache_control_10s(self):
        _make_publicado(slug="post-1")
        client = APIClient()
        response = client.get(_list_url("post-1"))
        assert "max-age=10" in response.get("Cache-Control", "")


@pytest.mark.django_db
class TestCreateComment:
    def test_anonymous_cannot_create(self):
        _make_publicado(slug="post-1")
        client = APIClient()
        response = client.post(
            _list_url("post-1"), {"conteudo": "Comentário pastoral"}, format="json"
        )
        assert response.status_code in (401, 403)

    def test_authenticated_creates_comment(self):
        post = _make_publicado(slug="post-1")
        customer = BlogCustomerFactory()
        client = APIClient()
        client.force_authenticate(user=customer)
        response = client.post(
            _list_url("post-1"),
            {"conteudo": "Comentário pastoral relevante"},
            format="json",
            HTTP_X_FORWARDED_FOR="203.0.113.10",
        )
        assert response.status_code == 201, response.content
        comment = Comentario.objects.first()
        assert comment.customer == customer
        assert comment.post == post
        assert comment.ip_address == "203.0.113.10"

    def test_too_short_conteudo_returns_400(self):
        _make_publicado(slug="post-1")
        customer = BlogCustomerFactory()
        client = APIClient()
        client.force_authenticate(user=customer)
        response = client.post(
            _list_url("post-1"), {"conteudo": "ab"}, format="json"
        )
        assert response.status_code == 400

    def test_create_on_rascunho_returns_404(self):
        PostFactory(slug="rascunho-x", status=PostStatus.RASCUNHO)
        customer = BlogCustomerFactory()
        client = APIClient()
        client.force_authenticate(user=customer)
        response = client.post(
            _list_url("rascunho-x"),
            {"conteudo": "tentativa"},
            format="json",
        )
        assert response.status_code == 404

    def test_rate_limit_5_per_minute(self):
        _make_publicado(slug="post-1")
        customer = BlogCustomerFactory()
        client = APIClient()
        client.force_authenticate(user=customer)
        # 5 chamadas OK, 6ª deve dar 429
        for i in range(5):
            response = client.post(
                _list_url("post-1"),
                {"conteudo": f"comentario numero {i}"},
                format="json",
            )
            assert response.status_code == 201, (i, response.content)
        response = client.post(
            _list_url("post-1"),
            {"conteudo": "comentario sexto"},
            format="json",
        )
        assert response.status_code == 429
        assert response.json().get("code") == "rate_limit_exceeded"


@pytest.mark.django_db
class TestUpdateComment:
    def test_owner_can_patch_within_15min(self):
        c = ComentarioFactory(conteudo="Original 123")
        client = APIClient()
        client.force_authenticate(user=c.customer)
        response = client.patch(
            _detail_url(c.id), {"conteudo": "Editado pastorale"}, format="json"
        )
        assert response.status_code == 200, response.content
        c.refresh_from_db()
        assert c.conteudo == "Editado pastorale"

    def test_patch_after_15min_returns_400(self):
        c = ComentarioFactory(conteudo="Original 123")
        client = APIClient()
        client.force_authenticate(user=c.customer)
        future = timezone.now() + timezone.timedelta(minutes=20)
        with patch("clama.blog.views.timezone.now", return_value=future):
            response = client.patch(
                _detail_url(c.id),
                {"conteudo": "Tarde demais 123"},
                format="json",
            )
        assert response.status_code == 400
        body = response.json()
        assert "comentario_muito_antigo" in str(body)

    def test_non_owner_cannot_patch(self):
        c = ComentarioFactory()
        outro = BlogCustomerFactory()
        client = APIClient()
        client.force_authenticate(user=outro)
        response = client.patch(
            _detail_url(c.id), {"conteudo": "Nao posso 123"}, format="json"
        )
        assert response.status_code == 403


@pytest.mark.django_db
class TestDeleteComment:
    def test_owner_can_delete(self):
        c = ComentarioFactory()
        client = APIClient()
        client.force_authenticate(user=c.customer)
        response = client.delete(_detail_url(c.id))
        assert response.status_code == 204
        assert not Comentario.objects.filter(id=c.id).exists()

    def test_admin_can_delete_any(self):
        c = ComentarioFactory()
        admin = BlogUserFactory(is_clama_admin=True)
        client = APIClient()
        client.force_authenticate(user=admin)
        response = client.delete(_detail_url(c.id))
        assert response.status_code == 204

    def test_other_customer_cannot_delete(self):
        c = ComentarioFactory()
        outro = BlogCustomerFactory()
        client = APIClient()
        client.force_authenticate(user=outro)
        response = client.delete(_detail_url(c.id))
        assert response.status_code == 403
