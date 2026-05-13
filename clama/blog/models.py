import uuid

from django.conf import settings
from django.db import models

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
