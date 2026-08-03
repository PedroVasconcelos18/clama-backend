"""Views REST do app blog.

`PostViewSet` é o CRUD admin do Post. Endpoints públicos de leitura
viram em stories futuras (3.1) e ficarão em outra view com `AllowAny`.
"""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q
from django.http import Http404
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
from rest_framework.views import APIView

from clama_backend.users.permissions import IsClamaAdmin

from .models import (
    Comentario,
    CustomerBanido,
    Post,
    PostEspelho,
    PostStatus,
    Reacao,
    ReacaoTipo,
)
from .permissions import IsUnbannedCustomer
from .serializers import (
    AdminComentarioSerializer,
    ComentarioSerializer,
    CustomerBanidoCreateSerializer,
    CustomerBanidoListSerializer,
    PostCreateSerializer,
    PostDetailSerializer,
    PostListSerializer,
    PostPublicListSerializer,
    PostPublicSerializer,
)
from .services.espelho import (
    PostNaoAceitaInteracao,
    PostNaoEncontrado,
    resolver_espelho,
)
from .services.wordpress_client import WordPressIndisponivel

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

    def _ancoras(self) -> tuple[Post | None, "PostEspelho | None"]:
        """Resolve as duas âncoras possíveis do comentário.

        Durante a transição um post pode existir só no CMS próprio (legado),
        só no WordPress, ou nos dois (migrado no Epic 4). Preencher as duas
        quando as duas existem é o que o `WP-FR32` pede durante a validação.

        A resolução do espelho é **sob demanda** (Story 3.10): a ordem de
        eventos não garante que o webhook já tenha chegado, e o primeiro
        leitor a comentar num post recém-publicado receberia erro de FK.
        """
        slug = self.kwargs["slug"]

        post = Post.objects.filter(slug=slug, status=PostStatus.PUBLICADO).first()
        espelho = None

        try:
            espelho = resolver_espelho(slug)
        except PostNaoAceitaInteracao:
            # O espelho existe e diz que o post não está publicado. Isso vence
            # o legado: o WordPress é a fonte da verdade sobre o estado.
            raise
        except (PostNaoEncontrado, WordPressIndisponivel):
            # Sem espelho e sem WordPress: se há post legado publicado, o
            # caminho antigo ainda serve. Se não há, o 404 abaixo responde.
            if post is None:
                raise

        if post is None and espelho is None:
            raise PostNaoEncontrado()

        return post, espelho

    def get_queryset(self):
        slug = self.kwargs["slug"]
        post = Post.objects.filter(slug=slug, status=PostStatus.PUBLICADO).first()

        if post is not None:
            # Durante a transição um post migrado tem comentários nas duas
            # colunas; o OR evita que os antigos sumam da listagem.
            return Comentario.objects.filter(
                Q(post=post) | Q(post_espelho__slug=slug)
            ).distinct()

        espelho = PostEspelho.objects.filter(slug=slug).first()
        if espelho is None:
            raise Http404
        return Comentario.objects.filter(post_espelho=espelho)

    def perform_create(self, serializer):
        if getattr(self.request, "limited", False):
            # Sinaliza pro `create()` retornar 429
            self._rate_limited = True
            return
        post, espelho = self._ancoras()
        serializer.save(
            post=post,
            post_espelho=espelho,
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
            # FR49: noindex se há comentários novos (<24h) que ainda não
            # passaram pelo radar da moderação — protege SEO contra ofensas
            # publicadas mas não-deletadas.
            cutoff = timezone.now() - timedelta(hours=24)
            try:
                post = self.get_post()
            except Exception:
                post = None
            if (
                post
                and Comentario.objects.filter(post=post, created_at__gt=cutoff).exists()
            ):
                response["X-Robots-Tag"] = "noindex"
        return response


class ComentarioUpdateDestroyView(generics.RetrieveUpdateDestroyAPIView):
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

    return ValidationError({"code": code, "pastoral_message": message})


@method_decorator(
    ratelimit(key="user", rate="30/m", method="POST", block=False),
    name="post",
)
class ReacaoToggleView(APIView):
    """Toggle like de um post.

    POST cria a reação se ainda não existe (liked=true) ou deleta se já
    existe (liked=false). Retorna `like_count` atualizado para o
    frontend renderizar.
    """

    permission_classes = [IsUnbannedCustomer]
    http_method_names = ["post", "head", "options"]

    @extend_schema(
        request=None,
        responses={
            200: OpenApiResponse(description='{"liked": bool, "like_count": int}')
        },
        summary="Toggle like de um post",
    )
    def post(self, request, slug, *args, **kwargs):
        if getattr(request, "limited", False):
            return Response(
                {
                    "code": "rate_limit_exceeded",
                    "pastoral_message": (
                        "Calma! Aguarde um momento antes de reagir de novo."
                    ),
                },
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )
        post = Post.objects.filter(slug=slug, status=PostStatus.PUBLICADO).first()
        espelho = None

        try:
            espelho = resolver_espelho(slug)
        except PostNaoAceitaInteracao:
            raise
        except (PostNaoEncontrado, WordPressIndisponivel):
            if post is None:
                raise

        if post is None and espelho is None:
            raise PostNaoEncontrado()

        # O filtro precisa casar a âncora que a linha realmente usa: um like
        # gravado só no espelho não seria encontrado por `filter(post=post)`,
        # e a pessoa acabaria com dois likes no mesmo post.
        filtro = Q(post=post) if post is not None else Q(post_espelho=espelho)
        if post is not None and espelho is not None:
            filtro = Q(post=post) | Q(post_espelho=espelho)

        with transaction.atomic():
            existing = (
                Reacao.objects.select_for_update()
                .filter(filtro, customer=request.user, tipo=ReacaoTipo.LIKE)
                .first()
            )
            if existing is not None:
                existing.delete()
                liked = False
            else:
                Reacao.objects.create(
                    post=post,
                    post_espelho=espelho,
                    customer=request.user,
                    tipo=ReacaoTipo.LIKE,
                )
                liked = True

        if post is not None:
            contagem = post.like_count
        else:
            contagem = espelho.reacoes.filter(tipo=ReacaoTipo.LIKE).count()

        return Response({"liked": liked, "like_count": contagem})


class AdminCommentsViewSet(viewsets.ModelViewSet):
    """Admin lista/deleta qualquer comentário; filtra por suspeitos ou post."""

    queryset = Comentario.objects.all().select_related("post", "customer")
    serializer_class = AdminComentarioSerializer
    permission_classes = [IsClamaAdmin]
    pagination_class = BlogPostPagination
    lookup_field = "id"
    lookup_value_regex = "[0-9a-fA-F-]{36}"
    http_method_names = ["get", "delete", "head", "options"]

    def get_queryset(self):
        qs = super().get_queryset()
        status_param = self.request.query_params.get("status")
        if status_param == "suspeitos":
            qs = qs.filter(is_suspeito=True)
        post_slug = self.request.query_params.get("post")
        if post_slug:
            qs = qs.filter(post__slug=post_slug)
        return qs.order_by("-created_at")


class AdminBannedCustomersViewSet(viewsets.ModelViewSet):
    """Admin gerencia banimentos ATIVOS — list, create (idempotente), destroy
    (revoga por customer_id).
    """

    queryset = CustomerBanido.objects.filter(revogado_em__isnull=True).select_related(
        "customer", "banido_por"
    )
    permission_classes = [IsClamaAdmin]
    pagination_class = BlogPostPagination
    lookup_field = "customer_id"
    # User.id é BigAutoField (inteiro), não UUID
    lookup_value_regex = r"\d+"
    http_method_names = ["get", "post", "delete", "head", "options"]

    def get_serializer_class(self):
        if self.action == "create":
            return CustomerBanidoCreateSerializer
        return CustomerBanidoListSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        customer_id = serializer.validated_data["customer_id"]
        motivo = serializer.validated_data["motivo"]
        User = get_user_model()
        try:
            customer = User.objects.get(id=customer_id)
        except User.DoesNotExist:
            return Response(
                {
                    "code": "customer_nao_encontrado",
                    "pastoral_message": "Customer não encontrado.",
                },
                status=status.HTTP_404_NOT_FOUND,
            )
        # Não permite banir outro admin (nem si mesmo). IsUnbannedCustomer
        # já tem admin-override (admins não são bloqueados), mas criar
        # registros de ban contra admins gera confusão de auditoria.
        if getattr(customer, "is_clama_admin", False):
            return Response(
                {
                    "code": "cannot_ban_admin",
                    "pastoral_message": (
                        "Admins não podem ser banidos. Para remover acesso, "
                        "edite a flag is_clama_admin diretamente."
                    ),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        # Idempotente: se já existe ban ativo, retorna o existente.
        existing = CustomerBanido.objects.filter(
            customer=customer, revogado_em__isnull=True
        ).first()
        if existing is not None:
            return Response(
                CustomerBanidoListSerializer(existing).data,
                status=status.HTTP_200_OK,
            )
        ban = CustomerBanido.objects.create(
            customer=customer, motivo=motivo, banido_por=request.user
        )
        return Response(
            CustomerBanidoListSerializer(ban).data,
            status=status.HTTP_201_CREATED,
        )

    def destroy(self, request, *args, **kwargs):
        customer_id = kwargs.get("customer_id")
        ban = CustomerBanido.objects.filter(
            customer_id=customer_id, revogado_em__isnull=True
        ).first()
        if ban is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        ban.revogado_em = timezone.now()
        ban.revogado_por = request.user
        ban.save()
        return Response(status=status.HTTP_204_NO_CONTENT)
