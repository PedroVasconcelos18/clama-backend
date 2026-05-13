"""Views REST do app blog.

`PostViewSet` é o CRUD admin do Post. Endpoints públicos de leitura
viram em stories futuras (3.1) e ficarão em outra view com `AllowAny`.
"""

from datetime import timedelta

from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.decorators import method_decorator
from django_ratelimit.decorators import ratelimit
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import generics, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from clama_backend.users.permissions import IsClamaAdmin

from .models import Comentario, Post, PostStatus
from .permissions import IsCommentOwner, IsUnbannedCustomer
from .serializers import (
    ComentarioSerializer,
    PostCreateSerializer,
    PostDetailSerializer,
    PostListSerializer,
    PostPublicListSerializer,
    PostPublicSerializer,
)

COMENTARIO_EDIT_WINDOW = timedelta(minutes=15)


def _client_ip(request) -> str:
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "")


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


class BlogPublicPagination(PageNumberPagination):
    page_size = 12
    page_size_query_param = "page_size"
    max_page_size = 50


class PostPublicViewSet(viewsets.ReadOnlyModelViewSet):
    """Endpoints públicos de leitura do blog (sem auth).

    Apenas posts com `status=PUBLICADO` aparecem. lookup por slug.
    Frontend Vike SSG consome esses endpoints no build pra prerender.
    """

    queryset = Post.objects.publicados()
    lookup_field = "slug"
    lookup_value_regex = r"[-\w]+"
    permission_classes = [AllowAny]
    pagination_class = BlogPublicPagination

    def get_serializer_class(self):
        if self.action == "list":
            return PostPublicListSerializer
        return PostPublicSerializer

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        # Hint pro CDN/browser cachearem 5min — Vercel SSG faz o trabalho
        # pesado; este header reduz pressão em casos de bypass do edge cache.
        if request.method in ("GET", "HEAD"):
            response["Cache-Control"] = "public, max-age=300"
        return response


@method_decorator(
    ratelimit(key="user", rate="5/m", method="POST", block=False),
    name="post",
)
class ComentarioListCreateView(generics.ListCreateAPIView):
    """Lista comentários públicos do post e permite customer criar.

    GET: AllowAny, cache 10s.
    POST: IsUnbannedCustomer, rate-limited 5/min/user, IP capturado.
    """

    serializer_class = ComentarioSerializer
    pagination_class = BlogPostPagination

    def get_permissions(self):
        if self.request.method == "POST":
            return [IsUnbannedCustomer()]
        return [AllowAny()]

    def get_post(self) -> Post:
        return get_object_or_404(
            Post, slug=self.kwargs["slug"], status=PostStatus.PUBLICADO
        )

    def get_queryset(self):
        post = self.get_post()
        return Comentario.objects.filter(post=post)

    def perform_create(self, serializer):
        if getattr(self.request, "limited", False):
            # Sinaliza pro `create()` retornar 429
            self._rate_limited = True
            return
        post = self.get_post()
        serializer.save(
            post=post,
            customer=self.request.user,
            ip_address=_client_ip(self.request),
        )

    def create(self, request, *args, **kwargs):
        # Pre-validate, then check rate limit BEFORE saving — devolve mensagem
        # pastoral em 429 em vez do default do django-ratelimit.
        if getattr(request, "limited", False):
            return Response(
                {
                    "code": "rate_limit_exceeded",
                    "pastoral_message": (
                        "Calma! Aguarde um momento antes de comentar de novo."
                    ),
                },
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )
        return super().create(request, *args, **kwargs)

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        if request.method in ("GET", "HEAD"):
            response["Cache-Control"] = "public, max-age=10"
        return response


class ComentarioUpdateDestroyView(
    generics.RetrieveUpdateDestroyAPIView
):
    """PATCH/DELETE de comentário individual.

    PATCH: owner only, dentro de 15min da criação.
    DELETE: owner OR admin clama.
    """

    queryset = Comentario.objects.all()
    serializer_class = ComentarioSerializer
    lookup_field = "id"
    lookup_value_regex = "[0-9a-fA-F-]{36}"
    permission_classes = [IsAuthenticated]
    http_method_names = ["patch", "delete", "head", "options", "get"]

    def get_object(self):
        obj = super().get_object()
        # Para DELETE, admin tem override; para PATCH, apenas owner.
        if self.request.method == "DELETE":
            is_owner = obj.customer_id == self.request.user.id
            is_admin = getattr(self.request.user, "is_clama_admin", False)
            if not (is_owner or is_admin):
                raise PermissionDenied(detail="Sem permissão para apagar.")
        else:
            # PATCH/GET — apenas owner
            if obj.customer_id != self.request.user.id:
                raise PermissionDenied(detail="Sem permissão para editar.")
        return obj

    def perform_update(self, serializer):
        instance = serializer.instance
        age = timezone.now() - instance.created_at
        if age > COMENTARIO_EDIT_WINDOW:
            raise serializers_validation_error(
                "comentario_muito_antigo",
                "Esse comentário foi escrito há mais de 15 minutos e "
                "não pode mais ser editado.",
            )
        serializer.save()


def serializers_validation_error(code: str, message: str):
    from rest_framework.exceptions import ValidationError

    return ValidationError(
        {"code": code, "pastoral_message": message}
    )
