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
    SIMPLES_GRATUITA = "simples_gratuita", "Simples Gratuita"


class PlanManager(models.Manager):
    """Manager customizado para Plan."""

    def infer_from_valor(self, valor_centavos: int) -> "Plan | None":
        """
        Infere o plano ativo apropriado para um dado valor em centavos.

        Regra "par abaixo": retorna o plano ativo (e visível) de maior
        `valor_centavos` cujo valor seja menor ou igual ao informado.
        Se nenhum plano ativo bater (ex.: valor abaixo do menor plano —
        caso o serializer já valida antes), retorna o menor plano ativo
        e visível como fallback.

        Planos invisíveis (ex.: plano "Gratuito" do fluxo freemium) NÃO
        entram nesse "infer" — eles só são selecionados explicitamente
        pelo seu fluxo dedicado.

        Returns:
            Plan inferido ou None se não houver planos ativos visíveis.
        """
        abaixo = (
            self.filter(ativo=True, visivel=True, valor_centavos__lte=valor_centavos)
            .order_by("-valor_centavos")
            .first()
        )
        if abaixo is not None:
            return abaixo
        return (
            self.filter(ativo=True, visivel=True).order_by("valor_centavos").first()
        )


class Plan(UUIDPKModel, TimestampedModel):
    """
    Representa um plano de oferta do Clama.
    """

    nome = models.CharField(max_length=80)
    valor_centavos = models.IntegerField(
        validators=[MinValueValidator(1, message="Valor mínimo é R$ 0,01")]
    )
    descricao = models.TextField()
    complexidade = models.CharField(
        max_length=30,
        choices=Complexidade.choices,
        default=Complexidade.SIMPLES,
    )
    ordem = models.PositiveSmallIntegerField(default=1)
    ativo = models.BooleanField(default=True)
    visivel = models.BooleanField(
        default=True,
        help_text=(
            "Indica se o plano aparece para o usuário final (LP, formulário). "
            "Planos invisíveis (ex.: Gratuito do freemium) só são usados via "
            "fluxos dedicados."
        ),
    )

    objects = PlanManager()

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
