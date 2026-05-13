import pytest
from django.test import Client
from django.utils import timezone

from clama.blog.models import PostStatus
from clama.blog.sitemaps import PostSitemap
from clama.blog.tests.factories import PostFactory


@pytest.mark.django_db
class TestPostSitemap:
    def test_items_only_returns_publicados(self):
        rascunho = PostFactory(status=PostStatus.RASCUNHO)
        publicado = PostFactory(
            status=PostStatus.PUBLICADO, data_publicacao=timezone.now()
        )
        sitemap = PostSitemap()
        items = list(sitemap.items())
        ids = {p.id for p in items}
        assert publicado.id in ids
        assert rascunho.id not in ids

    def test_location_format(self):
        post = PostFactory(
            status=PostStatus.PUBLICADO,
            data_publicacao=timezone.now(),
            slug="meu-post-1",
        )
        sitemap = PostSitemap()
        assert sitemap.location(post) == "/blog/meu-post-1"

    def test_lastmod_is_updated_at(self):
        post = PostFactory(
            status=PostStatus.PUBLICADO, data_publicacao=timezone.now()
        )
        sitemap = PostSitemap()
        assert sitemap.lastmod(post) == post.updated_at


@pytest.mark.django_db
class TestSitemapRoute:
    def test_sitemap_xml_returns_200_xml(self):
        PostFactory(
            status=PostStatus.PUBLICADO,
            data_publicacao=timezone.now(),
            slug="post-um",
        )
        client = Client()
        response = client.get("/sitemap.xml")
        assert response.status_code == 200
        content = response.content.decode()
        assert "<?xml" in content
        assert "/blog/post-um" in content

    def test_sitemap_xml_excludes_rascunhos(self):
        PostFactory(status=PostStatus.RASCUNHO, slug="rascunho-um")
        PostFactory(
            status=PostStatus.PUBLICADO,
            data_publicacao=timezone.now(),
            slug="publicado-um",
        )
        client = Client()
        response = client.get("/sitemap.xml")
        body = response.content.decode()
        assert "/blog/rascunho-um" not in body
        assert "/blog/publicado-um" in body


@pytest.mark.django_db
class TestRobotsRoute:
    def test_robots_txt_returns_200_text(self):
        client = Client()
        response = client.get("/robots.txt")
        assert response.status_code == 200
        assert response["Content-Type"].startswith("text/plain")
        body = response.content.decode()
        assert "User-agent: *" in body
        assert "Allow: /blog/" in body
        assert "Disallow: /api/" in body
        assert "Disallow: /admin/" in body
        assert "Sitemap:" in body
