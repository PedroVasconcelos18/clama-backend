"""Sitemap XML do blog — apenas posts publicados."""

from django.contrib.sitemaps import Sitemap

from .models import Post


class PostSitemap(Sitemap):
    changefreq = "weekly"
    priority = 0.7

    def items(self):
        return Post.objects.publicados()

    def lastmod(self, obj: Post):
        return obj.updated_at

    def location(self, obj: Post) -> str:
        return f"/blog/{obj.slug}"
