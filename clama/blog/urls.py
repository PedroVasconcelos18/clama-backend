"""URLs do app blog."""

from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    ComentarioListCreateView,
    ComentarioUpdateDestroyView,
    PostPublicViewSet,
    PostViewSet,
    ReacaoToggleView,
)

router = DefaultRouter()
router.register(r"blog/posts", PostViewSet, basename="blog-post")
router.register(
    r"blog/public/posts", PostPublicViewSet, basename="blog-post-public"
)

urlpatterns = router.urls + [
    path(
        "blog/posts/<slug:slug>/comments/",
        ComentarioListCreateView.as_view(),
        name="comentarios-list-create",
    ),
    path(
        "blog/comments/<uuid:id>/",
        ComentarioUpdateDestroyView.as_view(),
        name="comentario-detail",
    ),
    path(
        "blog/posts/<slug:slug>/like/",
        ReacaoToggleView.as_view(),
        name="reacao-toggle",
    ),
]
