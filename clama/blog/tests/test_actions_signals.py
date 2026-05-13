from unittest.mock import patch

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from clama.blog.models import Post, PostStatus
from clama.blog.tests.factories import BlogUserFactory, PostFactory

POSTS_URL = "/api/blog/posts/"


def _action_url(post_id, action_name):
    return f"{POSTS_URL}{post_id}/{action_name}/"


def _admin_client():
    client = APIClient()
    admin = BlogUserFactory(is_clama_admin=True)
    client.force_authenticate(user=admin)
    return client, admin


def _non_admin_client():
    from django.contrib.auth import get_user_model

    User = get_user_model()
    user = User.objects.create_user(email="x@y.test", password="x")
    user.is_clama_admin = False
    user.save()
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.mark.django_db
class TestTransitarPara:
    def test_rascunho_para_publicado_sets_data_publicacao(self):
        post = PostFactory(status=PostStatus.RASCUNHO, data_publicacao=None)
        before = timezone.now()
        post.transitar_para(PostStatus.PUBLICADO)
        assert post.status == PostStatus.PUBLICADO
        assert post.data_publicacao is not None
        assert post.data_publicacao >= before

    def test_publicado_para_rascunho_preserva_data_publicacao(self):
        original_data = timezone.now() - timezone.timedelta(days=3)
        post = PostFactory(
            status=PostStatus.PUBLICADO, data_publicacao=original_data
        )
        post.transitar_para(PostStatus.RASCUNHO)
        assert post.status == PostStatus.RASCUNHO
        # data_publicacao preservada como referência histórica
        assert post.data_publicacao == original_data

    def test_mesmo_status_e_no_op(self):
        post = PostFactory(status=PostStatus.RASCUNHO)
        original_updated_at = post.updated_at
        post.transitar_para(PostStatus.RASCUNHO)
        post.refresh_from_db()
        # updated_at não muda — save não foi chamado
        assert post.updated_at == original_updated_at

    def test_status_invalido_raises(self):
        post = PostFactory()
        with pytest.raises(ValueError, match="Status invalido"):
            post.transitar_para("excluido")

    def test_republicar_preserva_data_original(self):
        original_data = timezone.now() - timezone.timedelta(days=10)
        post = PostFactory(
            status=PostStatus.PUBLICADO, data_publicacao=original_data
        )
        post.transitar_para(PostStatus.RASCUNHO)
        post.transitar_para(PostStatus.PUBLICADO)
        assert post.status == PostStatus.PUBLICADO
        # data_publicacao da PRIMEIRA publicação preservada
        assert post.data_publicacao == original_data


@pytest.mark.django_db
class TestPublicarAction:
    def test_publicar_success(self):
        post = PostFactory(status=PostStatus.RASCUNHO)
        client, _ = _admin_client()
        with patch("clama.blog.signals.regenerar_blog_ssg.delay") as mock_regen, patch(
            "clama.blog.signals.notificar_indexnow.delay"
        ) as mock_indexnow:
            response = client.post(_action_url(post.id, "publicar"))
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == PostStatus.PUBLICADO
        assert body["data_publicacao"] is not None
        post.refresh_from_db()
        assert post.status == PostStatus.PUBLICADO
        mock_regen.assert_called_with(str(post.id))
        mock_indexnow.assert_called_with(str(post.id))

    def test_publicar_requires_admin(self):
        post = PostFactory(status=PostStatus.RASCUNHO)
        client = _non_admin_client()
        response = client.post(_action_url(post.id, "publicar"))
        assert response.status_code == 403


@pytest.mark.django_db
class TestDespublicarAction:
    def test_despublicar_success(self):
        post = PostFactory(
            status=PostStatus.PUBLICADO, data_publicacao=timezone.now()
        )
        client, _ = _admin_client()
        with patch("clama.blog.signals.regenerar_blog_ssg.delay") as mock_regen, patch(
            "clama.blog.signals.notificar_indexnow.delay"
        ) as mock_indexnow:
            response = client.post(_action_url(post.id, "despublicar"))
        assert response.status_code == 200
        assert response.json()["status"] == PostStatus.RASCUNHO
        post.refresh_from_db()
        assert post.status == PostStatus.RASCUNHO
        mock_regen.assert_called_with(str(post.id))
        # IndexNow NÃO é chamado pra despublicar (não é "novo conteúdo crawlable")
        mock_indexnow.assert_not_called()

    def test_despublicar_requires_admin(self):
        post = PostFactory(status=PostStatus.PUBLICADO)
        client = _non_admin_client()
        response = client.post(_action_url(post.id, "despublicar"))
        assert response.status_code == 403


@pytest.mark.django_db
class TestPostSavedSignal:
    def test_signal_fires_on_save_to_publicado(self):
        with patch("clama.blog.signals.regenerar_blog_ssg.delay") as mock_regen, patch(
            "clama.blog.signals.notificar_indexnow.delay"
        ) as mock_indexnow:
            post = PostFactory(
                status=PostStatus.PUBLICADO, data_publicacao=timezone.now()
            )
        mock_regen.assert_called_with(str(post.id))
        mock_indexnow.assert_called_with(str(post.id))

    def test_signal_fires_regen_on_save_to_rascunho(self):
        # Despublicar dispara regen (pra remover post das listagens SSG)
        # mas NÃO chama IndexNow.
        with patch("clama.blog.signals.regenerar_blog_ssg.delay") as mock_regen, patch(
            "clama.blog.signals.notificar_indexnow.delay"
        ) as mock_indexnow:
            post = PostFactory(status=PostStatus.RASCUNHO)
        mock_regen.assert_called_with(str(post.id))
        mock_indexnow.assert_not_called()
