"""Serializers REST do app blog.

`PostCreateSerializer` aplica a camada 1 da defesa em profundidade
contra XSS: converte Tiptap JSON → HTML e sanitiza ANTES de chegar no
model. `Post.save()` (camada 2) re-sanitiza, garantindo o invariante
mesmo se um caminho alternativo de escrita aparecer.
"""

from rest_framework import serializers

from .models import Comentario, CustomerBanido, Post
from .sanitization import sanitize_post_html
from .tiptap_converter import tiptap_json_to_html


def _autor_nome(user) -> str:
    if user is None:
        return ""
    return user.nome_completo or user.email


def _autor_nome_publico(user) -> str:
    """Nome do autor para exposição pública.

    Honra `user.nome_format_blog` (FR32):
    - "completo" → "Juliana Silva" (intacto)
    - "compacto" (default) → "Juliana S." (primeiro nome + inicial)

    Fallback para 'Pedro' se autor None ou sem `nome_completo` — endpoint
    público NUNCA expõe email do autor.
    """
    if user is None:
        return "Pedro"
    nome = (user.nome_completo or "").strip()
    if not nome:
        return "Pedro"
    fmt = getattr(user, "nome_format_blog", "compacto")
    if fmt == "completo":
        return nome
    parts = nome.split()
    if len(parts) == 1:
        return parts[0]
    return f"{parts[0]} {parts[-1][0]}."


class PostListSerializer(serializers.ModelSerializer):
    """Serializer leve para listagens admin — NÃO expõe conteúdo pesado."""

    autor_nome = serializers.SerializerMethodField()

    class Meta:
        model = Post
        fields = [
            "id",
            "slug",
            "titulo",
            "excerpt",
            "status",
            "data_publicacao",
            "historia_ilustrativa",
            "autor",
            "autor_nome",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_autor_nome(self, obj: Post) -> str:
        return _autor_nome(obj.autor)


class PostDetailSerializer(serializers.ModelSerializer):
    """Serializer completo para reads do admin."""

    autor_nome = serializers.SerializerMethodField()

    class Meta:
        model = Post
        fields = [
            "id",
            "slug",
            "titulo",
            "conteudo_html",
            "conteudo_tiptap_json",
            "excerpt",
            "meta_title",
            "meta_description",
            "imagem_capa_url",
            "status",
            "data_publicacao",
            "historia_ilustrativa",
            "autor",
            "autor_nome",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_autor_nome(self, obj: Post) -> str:
        return _autor_nome(obj.autor)


class PostCreateSerializer(serializers.ModelSerializer):
    """Serializer para criação e update de posts via admin.

    `conteudo_html` NUNCA é aceito do cliente — é sempre derivado de
    `conteudo_tiptap_json` via converter + sanitização.
    """

    class Meta:
        model = Post
        fields = [
            "id",
            "slug",
            "titulo",
            "conteudo_tiptap_json",
            "conteudo_html",
            "excerpt",
            "meta_title",
            "meta_description",
            "imagem_capa_url",
            "status",
            "data_publicacao",
            "historia_ilustrativa",
            "autor",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "autor",
            "conteudo_html",
            "created_at",
            "updated_at",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._sanitized_html: str | None = None

    def validate_conteudo_tiptap_json(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError(
                "conteudo_tiptap_json deve ser um objeto JSON."
            )
        if value.get("type") != "doc":
            raise serializers.ValidationError(
                'conteudo_tiptap_json precisa ter type="doc" no topo.'
            )
        html_cru = tiptap_json_to_html(value)
        self._sanitized_html = sanitize_post_html(html_cru)
        return value

    def create(self, validated_data):
        validated_data["conteudo_html"] = self._sanitized_html or ""
        request = self.context.get("request")
        if request is not None and request.user.is_authenticated:
            validated_data["autor"] = request.user
        return super().create(validated_data)

    def update(self, instance, validated_data):
        if "conteudo_tiptap_json" in validated_data:
            validated_data["conteudo_html"] = self._sanitized_html or ""
        return super().update(instance, validated_data)


class PostPublicListSerializer(serializers.ModelSerializer):
    """Serializer público para listagens (sem conteudo_html)."""

    autor_nome = serializers.SerializerMethodField()
    like_count = serializers.IntegerField(read_only=True)
    comment_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Post
        fields = [
            "slug",
            "titulo",
            "excerpt",
            "imagem_capa_url",
            "data_publicacao",
            "historia_ilustrativa",
            "autor_nome",
            "like_count",
            "comment_count",
        ]
        read_only_fields = fields

    def get_autor_nome(self, obj: Post) -> str:
        return _autor_nome_publico(obj.autor)


class PostPublicSerializer(serializers.ModelSerializer):
    """Serializer público para detalhe (com conteudo_html)."""

    autor_nome = serializers.SerializerMethodField()
    like_count = serializers.IntegerField(read_only=True)
    comment_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Post
        fields = [
            "slug",
            "titulo",
            "conteudo_html",
            "excerpt",
            "meta_title",
            "meta_description",
            "imagem_capa_url",
            "data_publicacao",
            "historia_ilustrativa",
            "autor_nome",
            "like_count",
            "comment_count",
        ]
        read_only_fields = fields

    def get_autor_nome(self, obj: Post) -> str:
        return _autor_nome_publico(obj.autor)


class ComentarioSerializer(serializers.ModelSerializer):
    """Serializer público de comentários — não expõe email/IP."""

    customer_nome = serializers.SerializerMethodField()

    class Meta:
        model = Comentario
        fields = [
            "id",
            "post",
            "customer",
            "customer_nome",
            "conteudo",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "post",
            "customer",
            "customer_nome",
            "created_at",
            "updated_at",
        ]

    def get_customer_nome(self, obj: Comentario) -> str:
        return _autor_nome_publico(obj.customer)

    def validate_conteudo(self, value: str) -> str:
        if not value or len(value.strip()) < 3:
            raise serializers.ValidationError(
                {
                    "code": "comentario_invalido",
                    "pastoral_message": (
                        "Esse comentário precisa de um pouquinho mais de "
                        "texto pra ser publicado."
                    ),
                }
            )
        return value


class AdminComentarioSerializer(serializers.ModelSerializer):
    """Admin vê tudo: ip_address (decryptografado via ORM), customer email, etc."""

    post_slug = serializers.CharField(source="post.slug", read_only=True)
    post_titulo = serializers.CharField(source="post.titulo", read_only=True)
    customer_email = serializers.EmailField(source="customer.email", read_only=True)
    customer_nome = serializers.SerializerMethodField()

    class Meta:
        model = Comentario
        fields = [
            "id",
            "post",
            "post_slug",
            "post_titulo",
            "customer",
            "customer_email",
            "customer_nome",
            "conteudo",
            "is_suspeito",
            "ip_address",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_customer_nome(self, obj: Comentario) -> str:
        return _autor_nome_publico(obj.customer)


class CustomerBanidoListSerializer(serializers.ModelSerializer):
    customer_email = serializers.EmailField(source="customer.email", read_only=True)
    customer_nome = serializers.SerializerMethodField()
    banido_por_email = serializers.EmailField(
        source="banido_por.email", read_only=True
    )

    class Meta:
        model = CustomerBanido
        fields = [
            "id",
            "customer",
            "customer_email",
            "customer_nome",
            "motivo",
            "banido_em",
            "banido_por_email",
            "revogado_em",
        ]
        read_only_fields = fields

    def get_customer_nome(self, obj: CustomerBanido) -> str:
        return _autor_nome_publico(obj.customer)


class CustomerBanidoCreateSerializer(serializers.ModelSerializer):
    """Admin cria banimento informando customer + motivo.

    `banido_por` é injetado pela view do `request.user`. `customer_id` é
    IntegerField porque `users.User.id` é BigAutoField (não UUID — clama não
    tem model `Customer` separado).
    """

    customer_id = serializers.IntegerField(write_only=True)

    class Meta:
        model = CustomerBanido
        fields = [
            "id",
            "customer_id",
            "customer",
            "motivo",
            "banido_em",
            "banido_por",
            "revogado_em",
        ]
        read_only_fields = [
            "id",
            "customer",
            "banido_em",
            "banido_por",
            "revogado_em",
        ]

    def validate_motivo(self, value: str) -> str:
        if not value or len(value.strip()) < 3:
            raise serializers.ValidationError(
                "Informe um motivo para o banimento (≥3 caracteres)."
            )
        return value
