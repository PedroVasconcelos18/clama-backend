"""
Models do app instituicoes — instituições parceiras e ledger de repasse.
"""

from django.db import models

from clama.core.models import TimestampedModel, UUIDPKModel

# Logo é guardada como data-URI (base64) no próprio banco — sem storage externo
# nem redeploy. Limite baixo porque a data-URI viaja no payload público do dropdown.
LOGO_MAX_BYTES = 250 * 1024  # 250 KB
LOGO_ALLOWED_MIME = (
    "image/png",
    "image/jpeg",
    "image/svg+xml",
    "image/webp",
    "image/gif",
)


class RepasseStatus(models.TextChoices):
    REGISTRADO = "registrado", "Registrado"


class Instituicao(UUIDPKModel, TimestampedModel):
    """Instituição parceira elegível a receber repasse de doações."""

    nome = models.CharField(max_length=120)
    # Data-URI da logo (ex.: "data:image/png;base64,..."). Vazio = usa o fallback.
    logo = models.TextField(blank=True, default="")
    ativo = models.BooleanField(default=True)
    ordem = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["ordem", "nome"]
        verbose_name = "Instituição"
        verbose_name_plural = "Instituições"

    def __str__(self) -> str:
        return self.nome


class Repasse(UUIDPKModel, TimestampedModel):
    """Ledger imutável de repasse — snapshot de percentual e valor base por pedido."""

    pedido = models.OneToOneField(
        "orders.Pedido",
        on_delete=models.PROTECT,
        related_name="repasse",
    )
    instituicao = models.ForeignKey(
        "instituicoes.Instituicao",
        on_delete=models.PROTECT,
        related_name="repasses",
    )
    valor_base_centavos = models.IntegerField()
    percentual = models.PositiveSmallIntegerField()
    valor_centavos = models.IntegerField()
    status = models.CharField(
        max_length=20,
        choices=RepasseStatus.choices,
        default=RepasseStatus.REGISTRADO,
    )

    class Meta:
        verbose_name = "Repasse"
        verbose_name_plural = "Repasses"

    def __str__(self) -> str:
        return f"Repasse {self.valor_centavos} centavos (pedido {self.pedido_id})"
