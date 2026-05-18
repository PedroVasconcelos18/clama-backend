from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.sitemaps.views import sitemap
from django.urls import include, path
from django.views.generic import TemplateView
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularRedocView,
    SpectacularSwaggerView,
)
from rest_framework.routers import DefaultRouter

from clama.blog.sitemaps import PostSitemap

router = DefaultRouter()

sitemaps = {"blog": PostSitemap}

urlpatterns = [
    path(settings.ADMIN_URL, admin.site.urls),
    # API base URLs
    path("api/", include(router.urls)),
    # Core URLs (health check)
    path("api/", include("clama.core.urls")),
    # Plans API
    path("api/", include("clama.plans.api.urls")),
    # Orders API
    path("api/", include("clama.orders.api.urls")),
    # Payments API
    path("api/", include("clama.payments.api.urls")),
    # Notifications API (webhooks)
    path("api/", include("clama.notifications.api.urls")),
    # Freemium API (pedido gratuito)
    path("api/", include("clama.freemium.api.urls")),
    # Users API (admin auth)
    path("api/", include("clama_backend.users.api.urls")),
    # Customer API (login customer, /me, change-password) — spec lp-user-existence-gate.
    path("api/customer/", include("clama.customers.api.urls")),
    # Admin API (pedidos, metrics, planos, prompts)
    path("api/", include("clama.core.api.admin_urls")),
    # Blog API (admin CRUD; endpoints públicos virão na Story 3.1)
    path("api/", include("clama.blog.urls")),
    # Blog SEO infra
    path("sitemap.xml", sitemap, {"sitemaps": sitemaps}, name="sitemap"),
    path(
        "robots.txt",
        TemplateView.as_view(
            template_name="robots.txt",
            content_type="text/plain",
            extra_context={
                "sitemap_url": f"{settings.FRONTEND_PUBLIC_BLOG_BASE_URL.rstrip('/')}/sitemap.xml",
            },
        ),
        name="robots",
    ),
    # API Documentation
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("api/redoc/", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    if "debug_toolbar" in settings.INSTALLED_APPS:
        import debug_toolbar

        urlpatterns = [path("__debug__/", include(debug_toolbar.urls))] + urlpatterns

    # Sentry debug endpoint (apenas em DEBUG)
    from clama.core.views import SentryDebugView

    urlpatterns += [path("api/_sentry-debug/", SentryDebugView.as_view())]
