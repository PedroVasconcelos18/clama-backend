import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from clama.blog.models import Post, PostStatus
from clama.blog.tests.factories import BlogUserFactory, PostFactory

User = get_user_model()

POSTS_URL = "/api/blog/posts/"


def _post_url(post_id):
    return f"{POSTS_URL}{post_id}/"


def _admin_client(user=None):
    client = APIClient()
    admin = user or BlogUserFactory(is_clama_admin=True)
    client.force_authenticate(user=admin)
    return client, admin


def _non_admin_client():
    client = APIClient()
    user = User.objects.create_user(email="naoadmin@clama.test", password="x")
    user.is_clama_admin = False
    user.save()
    client.force_authenticate(user=user)
    return client, user


def _valid_tiptap_payload(slug="post-via-api"):
    return {
        "slug": slug,
        "titulo": "Post via API",
        "conteudo_tiptap_json": {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": "Mensagem pastoral"}],
                }
            ],
        },
        "excerpt": "Resumo",
    }


@pytest.mark.django_db
class TestListPosts:
    def test_list_requires_authentication(self):
        client = APIClient()
        response = client.get(POSTS_URL)
        assert response.status_code in (401, 403)

    def test_list_requires_admin(self):
        client, _ = _non_admin_client()
        response = client.get(POSTS_URL)
        assert response.status_code == 403

    def test_list_returns_paginated_posts(self):
        for _ in range(25):
            PostFactory()
        client, _ = _admin_client()
        response = client.get(POSTS_URL)
        assert response.status_code == 200
        body = response.json()
        assert body["count"] == 25
        assert len(body["results"]) == 20  # page_size default
        assert "next" in body
        assert "conteudo_html" not in body["results"][0]


@pytest.mark.django_db
class TestRetrievePost:
    def test_retrieve_returns_full_detail(self):
        post = PostFactory(titulo="Detalhe")
        client, _ = _admin_client()
        response = client.get(_post_url(post.id))
        assert response.status_code == 200
        body = response.json()
        assert body["titulo"] == "Detalhe"
        assert "conteudo_html" in body
        assert "conteudo_tiptap_json" in body
        assert "autor_nome" in body

    def test_retrieve_404_for_unknown_uuid(self):
        client, _ = _admin_client()
        response = client.get(_post_url("00000000-0000-0000-0000-000000000000"))
        assert response.status_code == 404


@pytest.mark.django_db
class TestCreatePost:
    def test_create_post_via_api(self):
        client, admin = _admin_client()
        response = client.post(POSTS_URL, _valid_tiptap_payload(), format="json")
        assert response.status_code == 201, response.content
        body = response.json()
        assert body["titulo"] == "Post via API"
        post = Post.objects.get(id=body["id"])
        assert post.autor == admin
        assert "<p>Mensagem pastoral</p>" in post.conteudo_html
        assert post.status == PostStatus.RASCUNHO

    def test_create_with_xss_is_sanitized(self):
        client, _ = _admin_client()
        payload = _valid_tiptap_payload(slug="xss-test")
        payload["conteudo_tiptap_json"]["content"][0]["content"][0]["text"] = (
            "<script>alert(1)</script>"
        )
        response = client.post(POSTS_URL, payload, format="json")
        assert response.status_code == 201, response.content
        post = Post.objects.get(id=response.json()["id"])
        assert "<script>" not in post.conteudo_html
        assert "&lt;script&gt;" in post.conteudo_html

    def test_create_invalid_tiptap_json_returns_400(self):
        client, _ = _admin_client()
        payload = _valid_tiptap_payload(slug="invalid")
        payload["conteudo_tiptap_json"] = "not a dict"
        response = client.post(POSTS_URL, payload, format="json")
        assert response.status_code == 400
        assert "conteudo_tiptap_json" in response.json()

    def test_create_with_status_publicado(self):
        client, _ = _admin_client()
        payload = _valid_tiptap_payload(slug="published-direct")
        payload["status"] = PostStatus.PUBLICADO
        response = client.post(POSTS_URL, payload, format="json")
        assert response.status_code == 201
        post = Post.objects.get(id=response.json()["id"])
        assert post.status == PostStatus.PUBLICADO

    def test_create_requires_admin(self):
        client, _ = _non_admin_client()
        response = client.post(POSTS_URL, _valid_tiptap_payload(), format="json")
        assert response.status_code == 403


@pytest.mark.django_db
class TestUpdatePost:
    def test_partial_update_post(self):
        post = PostFactory(titulo="Antigo")
        client, _ = _admin_client()
        response = client.patch(
            _post_url(post.id), {"titulo": "Novo"}, format="json"
        )
        assert response.status_code == 200
        post.refresh_from_db()
        assert post.titulo == "Novo"

    def test_update_re_sanitizes_when_tiptap_changes(self):
        post = PostFactory()
        client, _ = _admin_client()
        new_tiptap = {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": "atualizado"}],
                }
            ],
        }
        response = client.patch(
            _post_url(post.id),
            {"conteudo_tiptap_json": new_tiptap},
            format="json",
        )
        assert response.status_code == 200
        post.refresh_from_db()
        assert "atualizado" in post.conteudo_html


@pytest.mark.django_db
class TestDeletePost:
    def test_delete_post(self):
        post = PostFactory()
        client, _ = _admin_client()
        response = client.delete(_post_url(post.id))
        assert response.status_code == 204
        assert not Post.objects.filter(id=post.id).exists()

    def test_delete_requires_admin(self):
        post = PostFactory()
        client, _ = _non_admin_client()
        response = client.delete(_post_url(post.id))
        assert response.status_code == 403
        assert Post.objects.filter(id=post.id).exists()
