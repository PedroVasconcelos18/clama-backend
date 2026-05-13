"""Views REST do app blog.

`PostViewSet` é o CRUD admin do Post. Endpoints públicos de leitura
viram em stories futuras (3.1) e ficarão em outra view com `AllowAny`.
"""

from rest_framework import viewsets
from rest_framework.pagination import PageNumberPagination

from clama_backend.users.permissions import IsClamaAdmin

from .models import Post
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
