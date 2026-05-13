"""Views REST do app blog.

`PostViewSet` é o CRUD admin do Post. Endpoints públicos de leitura
viram em stories futuras (3.1) e ficarão em outra view com `AllowAny`.
"""

from django.db import transaction
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response

from clama_backend.users.permissions import IsClamaAdmin

from .models import Post, PostStatus
from .serializers import (
    PostCreateSerializer,
    PostDetailSerializer,
    PostListSerializer,
)


class BlogPostPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


class PostViewSet(viewsets.ModelViewSet):
    """CRUD admin de posts do blog."""

    queryset = Post.objects.all()
    lookup_field = "id"
    lookup_value_regex = "[0-9a-fA-F-]{36}"
    permission_classes = [IsClamaAdmin]
    pagination_class = BlogPostPagination

    def get_serializer_class(self):
        if self.action == "list":
            return PostListSerializer
        if self.action == "retrieve":
            return PostDetailSerializer
        return PostCreateSerializer

    @extend_schema(
        request=None,
        responses={200: OpenApiResponse(description="Publicação iniciada")},
        summary="Publica um post (transiciona para status=publicado)",
    )
    @action(detail=True, methods=["post"], url_path="publicar")
    def publicar(self, request, id=None):
        post = self.get_object()
        with transaction.atomic():
            post.transitar_para(PostStatus.PUBLICADO)
        return Response(
            {
                "id": str(post.id),
                "status": post.status,
                "data_publicacao": (
                    post.data_publicacao.isoformat() if post.data_publicacao else None
                ),
                "message": "Publicação iniciada — post no ar em ~3 minutos",
            }
        )

    @extend_schema(
        request=None,
        responses={200: OpenApiResponse(description="Despublicação iniciada")},
        summary="Despublica um post (transiciona para status=rascunho)",
    )
    @action(detail=True, methods=["post"], url_path="despublicar")
    def despublicar(self, request, id=None):
        post = self.get_object()
        with transaction.atomic():
            post.transitar_para(PostStatus.RASCUNHO)
        return Response(
            {
                "id": str(post.id),
                "status": post.status,
                "message": "Post despublicado — propagação em ~3 minutos",
            }
        )
