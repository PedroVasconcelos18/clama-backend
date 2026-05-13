import pytest
from django.db import IntegrityError
from django.utils import timezone

from clama.blog.models import Post, PostStatus
from clama.blog.tests.factories import PostFactory


@pytest.mark.django_db
class TestPostModel:
    def test_create_post_via_factory(self):
        post = PostFactory()
        assert post.pk is not None
        assert post.titulo
        assert post.slug

    def test_post_has_uuid_pk(self):
        post = PostFactory()
        assert len(str(post.id)) == 36

    def test_default_status_is_rascunho(self):
        post = PostFactory()
        assert post.status == PostStatus.RASCUNHO

    def test_str_returns_titulo(self):
        post = PostFactory(titulo="Como rezar com pureza de coração")
        assert str(post) == "Como rezar com pureza de coração"

    def test_timestamps_auto_set(self):
        post = PostFactory()
        assert post.created_at is not None
        assert post.updated_at is not None

    def test_slug_unique_constraint(self):
        PostFactory(slug="meu-slug")
        with pytest.raises(IntegrityError):
            PostFactory(slug="meu-slug")

    def test_data_publicacao_nullable(self):
        post = PostFactory()
        assert post.data_publicacao is None


@pytest.mark.django_db
class TestPostManager:
    def test_publicados_filters_published_only(self):
        PostFactory(status=PostStatus.RASCUNHO)
        published_1 = PostFactory(
            status=PostStatus.PUBLICADO,
            data_publicacao=timezone.now(),
        )
        published_2 = PostFactory(
            status=PostStatus.PUBLICADO,
            data_publicacao=timezone.now(),
        )

        publicados = Post.objects.publicados()

        assert publicados.count() == 2
        assert set(publicados.values_list("id", flat=True)) == {
            published_1.id,
            published_2.id,
        }

    def test_rascunhos_filters_drafts_only(self):
        PostFactory(status=PostStatus.PUBLICADO, data_publicacao=timezone.now())
        rascunho = PostFactory(status=PostStatus.RASCUNHO)

        rascunhos = Post.objects.rascunhos()

        assert rascunhos.count() == 1
        assert rascunhos.first().id == rascunho.id

    def test_publicados_ordered_by_data_publicacao_desc(self):
        old = PostFactory(
            status=PostStatus.PUBLICADO,
            data_publicacao=timezone.now() - timezone.timedelta(days=2),
        )
        new = PostFactory(
            status=PostStatus.PUBLICADO,
            data_publicacao=timezone.now(),
        )

        publicados = list(Post.objects.publicados())

        assert publicados[0].id == new.id
        assert publicados[1].id == old.id
