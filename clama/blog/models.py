import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone
from encrypted_model_fields.fields import EncryptedCharField

from clama.core.exceptions import ClamaBaseException
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


class PostEspelhoStatus(models.TextChoices):
    """Status espelhados do WordPress.

    Não reaproveita `PostStatus` de propósito: o WordPress tem estados que o
    CMS próprio nunca teve (`private`, `future`, `trash`), e colapsá-los em
    `rascunho`/`publicado` perderia justamente a informação que decide se o
    widget de comentários aparece.
    """

    RASCUNHO = "rascunho", "Rascunho"
    PUBLICADO = "publicado", "Publicado"
    PRIVADO = "privado", "Privado"
    AGENDADO = "agendado", "Agendado"
    LIXEIRA = "lixeira", "Lixeira"
    PENDENTE = "pendente", "Pendente de revisão"


class RemocaoDeEspelhoProibida(ClamaBaseException):
    """Tentativa de apagar linha do espelho (Story 3.4, AC7).

    O espelho nunca apaga: post removido no WordPress vira `LIXEIRA`. Apagar
    aqui derrubaria o `PROTECT` das FKs de `Comentario` e `Reacao` — ou, pior,
    passaria por cima delas quando não houvesse comentário ainda, deixando o
    espelho e o WordPress divergentes sem sinal nenhum.
    """

    code = "remocao_de_espelho_proibida"
    message = "PostEspelho nunca é removido; mude o status para LIXEIRA."
    pastoral_message = "Este registro não pode ser apagado."


class PostEspelhoQuerySet(models.QuerySet):
    """QuerySet que não apaga.

    Bloquear só o `delete()` da instância deixaria
    `PostEspelho.objects.filter(...).delete()` passar — e é justamente esse o
    caminho que um script de limpeza usaria.
    """

    def delete(self):
        raise RemocaoDeEspelhoProibida()

    def _remover_de_verdade(self):
        """Escotilha para correção de dado, fora do fluxo normal.

        Existe porque um espelho criado por engano (id de teste, ambiente
        trocado) não tem outro jeito de sair. Nome feio de propósito: quem
        escrever isto num handler vai ser perguntado por quê no PR.
        """
        return super().delete()


class PostEspelho(TimestampedModel):
    """Espelho local dos posts que vivem no WordPress (ADR-02).

    Existe para que moderação, resumo diário e dashboard continuem resolvendo
    por join local em vez de uma chamada de rede por linha. **Não é fonte da
    verdade** — o WordPress é. Nada aqui é editado por humano; o webhook da
    Story 3.2 escreve, a reconciliação da Story 3.6 corrige.

    O espelho **nunca apaga linha**: post removido no WordPress vira
    `LIXEIRA`. Apagar aqui derrubaria o `PROTECT` das FKs de `Comentario` e
    `Reacao`, que é o que preserva comentários e IPs sob a retenção de 6 meses
    do Marco Civil.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    wp_post_id = models.PositiveIntegerField(unique=True)
    # `db_index=False` porque o índice nomeado está declarado no `Meta`.
    # `SlugField` indexa por default, e deixar os dois cria duas árvores sobre
    # a mesma coluna — custo de escrita dobrado por nada.
    #
    # Não é `unique`: no WordPress um post na lixeira libera o slug, então dois
    # registros podem carregar o mesmo por um intervalo. A identidade aqui é
    # `wp_post_id`.
    slug = models.SlugField(max_length=200, db_index=False)
    titulo = models.CharField(max_length=200)
    status = models.CharField(
        max_length=20,
        choices=PostEspelhoStatus.choices,
        default=PostEspelhoStatus.RASCUNHO,
    )
    published_at = models.DateTimeField(null=True, blank=True)
    url = models.URLField(max_length=500, blank=True, default="")

    objects = PostEspelhoQuerySet.as_manager()

    class Meta:
        verbose_name = "Post espelhado"
        verbose_name_plural = "Posts espelhados"
        ordering = ["-published_at", "-created_at"]
        indexes = [
            # Listagem de comentários no painel filtra por slug do post.
            models.Index(fields=["slug"], name="idx_blog_postespelho_slug"),
            models.Index(
                fields=["status", "-published_at"],
                name="idx_blog_postesp_status_pub",
            ),
        ]

    def __str__(self) -> str:
        return self.titulo

    def delete(self, *args, **kwargs):
        """Invariante, não convenção (AC7 da Story 3.4).

        Um comentário sob a retenção de 6 meses do Marco Civil não pode
        depender de ninguém lembrar da regra. Aqui a regra é o código.
        """
        raise RemocaoDeEspelhoProibida()

    def _remover_de_verdade(self, *args, **kwargs):
        """Ver `PostEspelhoQuerySet._remover_de_verdade`."""
        return super().delete(*args, **kwargs)

    @property
    def aceita_interacao(self) -> bool:
        """Se comentário e reação podem ser criados neste post.

        Rascunho, lixeira e agendado não aceitam — o post não está público, e
        aceitar interação nele produziria comentário órfão de página visível.
        `PRIVADO` também não: quem enxerga é o operador logado no WordPress,
        e o widget do Clama não sabe disso.
        """
        return self.status == PostEspelhoStatus.PUBLICADO


class ReacaoTipo(models.TextChoices):
    LIKE = "like", "Like"
    # DISLIKE = "dislike", "Dislike"  # reservado pra Growth pós-MVP


class Comentario(TimestampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="comentarios")
    # Nullable de propósito: comentário novo em post do WordPress funciona de
    # ponta a ponta antes de o Epic 4 fazer o backfill das linhas antigas.
    #
    # `PROTECT` e não `CASCADE`: apagar um post não pode apagar comentário nem
    # o IP que fica sob a retenção de 6 meses do Marco Civil. O espelho também
    # nunca apaga linha — post removido no WordPress vira `LIXEIRA`.
    post_espelho = models.ForeignKey(
        "PostEspelho",
        on_delete=models.PROTECT,
        related_name="comentarios",
        null=True,
        blank=True,
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
            # Espelho do índice acima na coluna nova. Sem ele a listagem de
            # comentários do painel faz seq scan assim que passar a filtrar
            # por `post_espelho`.
            models.Index(
                fields=["post_espelho", "-created_at"],
                name="idx_blog_coment_espelho_crtd",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.customer.email}: {self.conteudo[:50]}"


class Reacao(TimestampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="reacoes")
    post_espelho = models.ForeignKey(
        "PostEspelho",
        on_delete=models.PROTECT,
        related_name="reacoes",
        null=True,
        blank=True,
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
            # A constraint acima atravessa a coluna FK legada e **não protege
            # a nova**: dois likes do mesmo customer no mesmo post pela coluna
            # `post_espelho` passariam por ela sem esbarrar em nada.
            #
            # O Postgres trata NULL como distinto em unique, então esta aqui
            # não bloqueia as linhas legadas — elas têm `post_espelho` nulo até
            # o backfill do Epic 4, e NULL nunca conflita com NULL.
            models.UniqueConstraint(
                fields=["post_espelho", "customer", "tipo"],
                name="uniq_blog_reacao_espelho_customer_tipo",
            ),
        ]
        indexes = [
            models.Index(fields=["post", "tipo"], name="idx_blog_reacao_post_tipo"),
            models.Index(
                fields=["post_espelho", "tipo"],
                name="idx_blog_reacao_espelho_tipo",
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
