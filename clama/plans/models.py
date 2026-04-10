"""
Models do app plans.
"""
from django.core.validators import MinValueValidator
from django.db import models

from clama.core.models import TimestampedModel, UUIDPKModel
from clama.core.money import centavos_to_reais_str


class Complexidade(models.TextChoices):
    SIMPLES = "simples", "Simples"
    COM_VERSICULO = "com_versiculo", "Com versículo"
    COM_PROFECIA_E_VERSICULOS = "com_profecia_e_versiculos", "Com profecia e versículos"


class Plan(UUIDPKModel, TimestampedModel):
    """
    Representa um plano de oferta do Clama.
    """

    nome = models.CharField(max_length=80)
    valor_centavos = models.IntegerField(
        validators=[MinValueValidator(2000, message="Valor mínimo é R$ 20,00")]
    )
    descricao = models.TextField()
    complexidade = models.CharField(
        max_length=30,
        choices=Complexidade.choices,
        default=Complexidade.SIMPLES,
    )
    ordem = models.PositiveSmallIntegerField(default=1)
    ativo = models.BooleanField(default=True)

    class Meta:
        ordering = ("ordem",)
        verbose_name = "plano"
        verbose_name_plural = "planos"

    def __str__(self):
        return f"{self.nome} - {self.valor_reais_str}"

    @property
    def valor_reais_str(self) -> str:
        """Retorna o valor formatado em reais (ex: 'R$ 20,00')."""
        return centavos_to_reais_str(self.valor_centavos)
