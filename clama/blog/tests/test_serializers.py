import pytest
from rest_framework.test import APIRequestFactory

from clama.blog.models import Post, PostStatus
from clama.blog.serializers import (
    PostCreateSerializer,
    PostDetailSerializer,
    PostListSerializer,
)
from clama.blog.tests.factories import BlogUserFactory, PostFactory


def _make_context(user):
    factory = APIRequestFactory()
    request = factory.post("/api/blog/posts/")
    request.user = user
    return {"request": request}


def _valid_payload(**overrides):
    payload = {
        "slug": "post-1",
        "titulo": "Como rezar com pureza",
        "conteudo_tiptap_json": {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": "Texto pastoral."}],
                }
            ],
        },
        "excerpt": "Resumo curto.",
        "status": PostStatus.RASCUNHO,
    }
    payload.update(overrides)
    return payload


@pytest.mark.django_db
class TestPostCreateSerializer:
    def test_create_valid_post(self):
        user = BlogUserFactory()
        serializer = PostCreateSerializer(
            data=_valid_payload(), context=_make_context(user)
        )
        assert serializer.is_valid(), serializer.errors
        post = serializer.save()
        assert post.titulo == "Como rezar com pureza"
        assert post.autor == user
        assert "<p>Texto pastoral.</p>" in post.conteudo_html
        assert post.conteudo_tiptap_json["type"] == "doc"

    def test_invalid_json_not_dict(self):
        user = BlogUserFactory()
        payload = _valid_payload(conteudo_tiptap_json="not a dict")
        serializer = PostCreateSerializer(
            data=payload, context=_make_context(user)
        )
        assert not serializer.is_valid()
        assert "conteudo_tiptap_json" in serializer.errors

    def test_invalid_json_missing_doc_type(self):
        user = BlogUserFactory()
        payload = _valid_payload(
            conteudo_tiptap_json={"type": "paragraph", "content": []}
        )
        serializer = PostCreateSerializer(
            data=payload, context=_make_context(user)
        )
        assert not serializer.is_valid()
        assert "conteudo_tiptap_json" in serializer.errors

    def test_xss_in_tiptap_json_is_sanitized(self):
        user = BlogUserFactory()
        payload = _valid_payload(
            conteudo_tiptap_json={
                "type": "doc",
                "content": [
                    {
                        "type": "paragraph",
                        "content": [
                            {"type": "text", "text": "<script>alert(1)</script>"}
                        ],
                    }
                ],
            }
        )
        serializer = PostCreateSerializer(
            data=payload, context=_make_context(user)
        )
        assert serializer.is_valid(), serializer.errors
        post = serializer.save()
        # Tag <script> literal não pode aparecer (XSS prevenido)
        assert "<script>" not in post.conteudo_html
        # Texto foi escapado e virou plaintext seguro
        assert "&lt;script&gt;" in post.conteudo_html
        # Wrapper <p> da estrutura Tiptap permanece (paragraph node)
        assert post.conteudo_html.startswith("<p>")

    def test_autor_setado_do_request_user(self):
        user = BlogUserFactory(email="autor1@clama.test")
        serializer = PostCreateSerializer(
            data=_valid_payload(), context=_make_context(user)
        )
        assert serializer.is_valid(), serializer.errors
        post = serializer.save()
        assert post.autor.email == "autor1@clama.test"

    def test_conteudo_html_is_read_only(self):
        # Cliente envia conteudo_html, deve ser ignorado
        user = BlogUserFactory()
        payload = _valid_payload()
        payload["conteudo_html"] = "<p>injected</p>"
        serializer = PostCreateSerializer(
            data=payload, context=_make_context(user)
        )
        assert serializer.is_valid(), serializer.errors
        post = serializer.save()
        assert "injected" not in post.conteudo_html

    def test_update_re_sanitizes_when_tiptap_changes(self):
        post = PostFactory()
        new_json = {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": "atualizado"}],
                }
            ],
        }
        serializer = PostCreateSerializer(
            instance=post,
            data={"conteudo_tiptap_json": new_json},
            partial=True,
            context=_make_context(post.autor),
        )
        assert serializer.is_valid(), serializer.errors
        updated = serializer.save()
        assert "atualizado" in updated.conteudo_html


@pytest.mark.django_db
class TestPostDetailSerializer:
    def test_detail_exposes_all_main_fields(self):
        post = PostFactory(titulo="Detail Test")
        data = PostDetailSerializer(post).data
        expected_keys = {
            "id",
            "slug",
            "titulo",
            "conteudo_html",
            "conteudo_tiptap_json",
            "excerpt",
            "meta_title",
            "meta_description",
            "imagem_capa_url",
            "status",
            "data_publicacao",
            "historia_ilustrativa",
            "autor",
            "autor_nome",
            "created_at",
            "updated_at",
        }
        assert expected_keys.issubset(set(data.keys()))
        assert data["titulo"] == "Detail Test"

    def test_autor_nome_falls_back_to_email(self):
        user = BlogUserFactory(email="x@clama.test")
        post = PostFactory(autor=user)
        data = PostDetailSerializer(post).data
        assert data["autor_nome"] == "x@clama.test"


@pytest.mark.django_db
class TestPostListSerializer:
    def test_list_omits_conteudo_html(self):
        post = PostFactory()
        data = PostListSerializer(post).data
        assert "conteudo_html" not in data

    def test_list_omits_conteudo_tiptap_json(self):
        post = PostFactory()
        data = PostListSerializer(post).data
        assert "conteudo_tiptap_json" not in data

    def test_list_includes_autor_nome(self):
        post = PostFactory()
        data = PostListSerializer(post).data
        assert "autor_nome" in data
