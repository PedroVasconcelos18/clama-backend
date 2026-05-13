import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone
from encrypted_model_fields.fields import EncryptedCharField

from clama.core.models import TimestampedModel

from .managers import PostManager
from .sanitization import sanitize_post_html


class PostStatus(models.TextChoices):
    RASCUNHO = "rascunho", "Rascunho"
    PUBLICADO = "publicado", "Publicado"


class Post(TimestampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    slug = models.SlugField(unique=True, max_length=200)
    titulo = models.CharField(max_length=200)
    conteudo_html = models.TextField()
    conteudo_tiptap_json = models.JSONField()
    excerpt = models.CharField(max_length=300, blank=True)
    meta_title = models.CharField(max_length=60, blank=True)
    meta_description = models.CharField(max_length=160, blank=True)
    imagem_capa_url = models.URLField(blank=True)
    status = models.CharField(
        max_length=20,
        choices=PostStatus.choices,
        default=PostStatus.RASCUNHO,
    )
    data_publicacao = models.DateTimeField(null=True, blank=True)
    autor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="posts_autorados",
    )
    historia_ilustrativa = models.BooleanField(default=False)

    objects = PostManager()

    class Meta:
        verbose_name = "Post"
        verbose_name_plural = "Posts"
        ordering = ["-data_publicacao", "-created_at"]
        indexes = [
            models.Index(
                fields=["status", "-data_publicacao"],
                name="idx_blog_post_status_pub",
            ),
            models.Index(fields=["slug"], name="idx_blog_post_slug"),
        ]

    def __str__(self):
        return self.titulo

    def save(self, *args, **kwargs):
        self.conteudo_html = sanitize_post_html(self.conteudo_html or "")
        super().save(*args, **kwargs)

    @property
    def comment_count(self) -> int:
        return self.comentarios.count()

    @property
    def like_count(self) -> int:
        return self.reacoes.filter(tipo=ReacaoTipo.LIKE).count()

    def transitar_para(self, novo_status: str) -> None:
        """Transita o status do post validando a maquina de estados.

        Estados validos: rascunho <-> publicado. Tentar outro estado raise
        ValueError. Transicionar para o mesmo status e no-op (nao salva).

        Quando transitando para PUBLICADO E data_publicacao ainda nao foi
        setada, registra agora como data de primeira publicacao. Re-publicar
        depois preserva a data original (referencia historica).
        """
        if novo_status not in PostStatus.values:
            raise ValueError(f"Status invalido: {novo_status!r}")
        if self.status == novo_status:
            return
        if novo_status == PostStatus.PUBLICADO and self.data_publicacao is None:
            self.data_publicacao = timezone.now()
        self.status = novo_status
        self.save()


class ReacaoTipo(models.TextChoices):
    LIKE = "like", "Like"
    # DISLIKE = "dislike", "Dislike"  # reservado pra Growth pós-MVP


class Comentario(TimestampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    post = models.ForeignKey(
        Post, on_delete=models.CASCADE, related_name="comentarios"
    )
    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="comentarios_blog",
    )
    conteudo = models.TextField(max_length=2000)
    ip_address = EncryptedCharField(max_length=45, blank=True, default="")
    is_suspeito = models.BooleanField(default=False)

    class Meta:
        verbose_name = "Comentário"
        verbose_name_plural = "Comentários"
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["post", "-created_at"],
                name="idx_blog_comentario_post_crtd",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.customer.email}: {self.conteudo[:50]}"


class Reacao(TimestampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    post = models.ForeignKey(
        Post, on_delete=models.CASCADE, related_name="reacoes"
    )
    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="reacoes_blog",
    )
    tipo = models.CharField(
        max_length=20,
        choices=ReacaoTipo.choices,
        default=ReacaoTipo.LIKE,
    )

    class Meta:
        verbose_name = "Reação"
        verbose_name_plural = "Reações"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["post", "customer", "tipo"],
                name="uniq_blog_reacao_post_customer_tipo",
            ),
        ]
        indexes = [
            models.Index(
                fields=["post", "tipo"], name="idx_blog_reacao_post_tipo"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.customer.email} {self.tipo} {self.post.slug}"


class CustomerBanido(TimestampedModel):
    """Banimento de customer do sistema de comentários do blog.

    Revogável via setar `revogado_em`/`revogado_por` (não delete — preserva
    histórico). Admin nunca é afetado (vide `IsUnbannedCustomer.has_permission`).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="banimentos",
    )
    motivo = models.TextField()
    banido_em = models.DateTimeField(auto_now_add=True)
    banido_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="banimentos_aplicados",
    )
    revogado_em = models.DateTimeField(null=True, blank=True)
    revogado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="banimentos_revogados",
    )

    class Meta:
        verbose_name = "Customer banido"
        verbose_name_plural = "Customers banidos"
        ordering = ["-banido_em"]
        indexes = [
            models.Index(
                fields=["customer", "revogado_em"],
                name="idx_blog_banido_cust_revog",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.customer.email} (revogado={self.revogado_em is not None})"
