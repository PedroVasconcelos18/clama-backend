import pytest
from django.db import IntegrityError, connection
from django.utils import timezone

from clama.blog.models import (
    Comentario,
    CustomerBanido,
    Post,
    PostStatus,
    Reacao,
    ReacaoTipo,
)
from clama.blog.tests.factories import (
    BlogCustomerFactory,
    BlogUserFactory,
    ComentarioFactory,
    CustomerBanidoFactory,
    PostFactory,
    ReacaoFactory,
)


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


@pytest.mark.django_db
class TestPostSaveSanitization:
    def test_save_strips_script_tag(self):
        post = PostFactory(conteudo_html="<script>alert(1)</script><p>safe</p>")
        post.refresh_from_db()
        assert "<script>" not in post.conteudo_html
        assert "alert" not in post.conteudo_html
        assert "<p>safe</p>" in post.conteudo_html

    def test_save_strips_iframe_tag(self):
        post = PostFactory(conteudo_html='<iframe src="x"></iframe><p>ok</p>')
        post.refresh_from_db()
        assert "<iframe" not in post.conteudo_html
        assert "<p>ok</p>" in post.conteudo_html

    def test_save_preserves_blockquote_class_versiculo(self):
        html = '<blockquote class="versiculo">João 3:16</blockquote>'
        post = PostFactory(conteudo_html=html)
        post.refresh_from_db()
        assert 'class="versiculo"' in post.conteudo_html
        assert "João 3:16" in post.conteudo_html

    def test_save_handles_empty_conteudo_html(self):
        post = PostFactory(conteudo_html="")
        post.refresh_from_db()
        assert post.conteudo_html == ""


@pytest.mark.django_db
class TestComentarioModel:
    def test_create_via_factory(self):
        c = ComentarioFactory()
        assert c.pk is not None
        assert c.conteudo
        assert c.post_id is not None
        assert c.customer_id is not None

    def test_default_is_suspeito_false(self):
        c = ComentarioFactory()
        assert c.is_suspeito is False

    def test_cascade_delete_when_post_deleted(self):
        post = PostFactory()
        ComentarioFactory(post=post)
        ComentarioFactory(post=post)
        assert Comentario.objects.filter(post=post).count() == 2
        post.delete()
        assert Comentario.objects.filter(post_id=post.id).count() == 0

    def test_str_truncates_conteudo(self):
        c = ComentarioFactory(conteudo="A" * 80)
        s = str(c)
        assert c.customer.email in s
        # conteúdo truncado em 50 chars
        assert "A" * 50 in s
        assert "A" * 51 not in s

    def test_ip_address_encrypted_at_rest(self):
        plain_ip = "203.0.113.42"
        ComentarioFactory(ip_address=plain_ip)
        # Query raw SQL pra verificar que o valor armazenado NÃO contém o IP plain
        with connection.cursor() as cursor:
            cursor.execute("SELECT ip_address FROM blog_comentario")
            stored = cursor.fetchone()[0]
        # O valor encriptado nunca contém o IP plain literal
        assert plain_ip not in str(stored)
        # Mas via ORM, decripta corretamente
        c = Comentario.objects.first()
        assert c.ip_address == plain_ip

    def test_post_has_comment_count_property(self):
        post = PostFactory()
        assert post.comment_count == 0
        ComentarioFactory(post=post)
        ComentarioFactory(post=post)
        assert post.comment_count == 2


@pytest.mark.django_db
class TestReacaoModel:
    def test_create_via_factory(self):
        r = ReacaoFactory()
        assert r.pk is not None
        assert r.tipo == ReacaoTipo.LIKE

    def test_default_tipo_is_like(self):
        post = PostFactory()
        customer = BlogCustomerFactory()
        r = Reacao.objects.create(post=post, customer=customer)
        assert r.tipo == ReacaoTipo.LIKE

    def test_unique_constraint_post_customer_tipo(self):
        post = PostFactory()
        customer = BlogCustomerFactory()
        ReacaoFactory(post=post, customer=customer, tipo=ReacaoTipo.LIKE)
        with pytest.raises(IntegrityError):
            ReacaoFactory(post=post, customer=customer, tipo=ReacaoTipo.LIKE)

    def test_post_has_like_count_property(self):
        post = PostFactory()
        assert post.like_count == 0
        ReacaoFactory(post=post)
        ReacaoFactory(post=post)
        ReacaoFactory(post=post)
        assert post.like_count == 3

    def test_cascade_delete_when_post_deleted(self):
        post = PostFactory()
        ReacaoFactory(post=post)
        ReacaoFactory(post=post)
        post.delete()
        assert Reacao.objects.filter(post_id=post.id).count() == 0


@pytest.mark.django_db
class TestCustomerBanidoModel:
    def test_create_via_factory(self):
        ban = CustomerBanidoFactory()
        assert ban.pk is not None
        assert ban.motivo
        assert ban.banido_em is not None
        assert ban.revogado_em is None

    def test_str_reflects_revogacao(self):
        c = BlogCustomerFactory(email="x@y.test")
        ban = CustomerBanidoFactory(customer=c)
        s = str(ban)
        assert "x@y.test" in s
        assert "revogado=False" in s
        ban.revogado_em = timezone.now()
        ban.save()
        assert "revogado=True" in str(ban)

    def test_banido_por_e_revogado_por_apontam_para_user(self):
        admin1 = BlogUserFactory(email="admin1@clama.test")
        admin2 = BlogUserFactory(email="admin2@clama.test")
        ban = CustomerBanidoFactory(banido_por=admin1)
        ban.revogado_por = admin2
        ban.revogado_em = timezone.now()
        ban.save()
        ban.refresh_from_db()
        assert ban.banido_por == admin1
        assert ban.revogado_por == admin2

    def test_cascade_delete_when_customer_deleted(self):
        c = BlogCustomerFactory()
        CustomerBanidoFactory(customer=c)
        CustomerBanidoFactory(customer=c)
        assert CustomerBanido.objects.filter(customer=c).count() == 2
        c.delete()
        assert CustomerBanido.objects.filter(customer_id=c.id).count() == 0

    def test_filter_active_banimentos(self):
        c = BlogCustomerFactory()
        active = CustomerBanidoFactory(customer=c)
        revogado = CustomerBanidoFactory(customer=c)
        revogado.revogado_em = timezone.now()
        revogado.save()
        active_qs = CustomerBanido.objects.filter(
            customer=c, revogado_em__isnull=True
        )
        assert active_qs.count() == 1
        assert active_qs.first().id == active.id
