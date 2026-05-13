"""URLs do app blog."""

from rest_framework.routers import DefaultRouter

from .views import PostPublicViewSet, PostViewSet

router = DefaultRouter()
router.register(r"blog/posts", PostViewSet, basename="blog-post")
router.register(
    r"blog/public/posts", PostPublicViewSet, basename="blog-post-public"
)

urlpatterns = router.urls
