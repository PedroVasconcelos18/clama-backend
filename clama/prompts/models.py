"""
Modelos do app prompts - Templates de prompt para geração de orações.
"""

from django.db import models, transaction

from clama.core.models import TimestampedModel, UUIDPKModel
from clama.prompts.managers import PromptTemplateManager


class PromptTemplate(UUIDPKModel, TimestampedModel):
    """
    Template de prompt para a geração de orações via Claude.

    Permite versionamento e evolução do tom pastoral sem necessidade de deploy.
    Apenas um template pode estar ativo por vez.
    """

    nome = models.CharField(
        max_length=80,
        unique=True,
        verbose_name="Nome",
    )
    versao = models.PositiveIntegerField(
        verbose_name="Versão",
    )
    system_prompt = models.TextField(
        verbose_name="System prompt",
        help_text="Prompt do sistema enviado ao Claude definindo a identidade do Clama.",
    )
    instrucoes_por_complexidade = models.JSONField(
        verbose_name="Instruções por complexidade",
        help_text="Dict mapeando complexidade do plano para instrução adicional.",
        default=dict,
    )
    ativo = models.BooleanField(
        default=False,
        verbose_name="Ativo",
        help_text="Apenas um template pode estar ativo por vez.",
    )

    objects = PromptTemplateManager()

    class Meta:
        verbose_name = "Template de Prompt"
        verbose_name_plural = "Templates de Prompt"
        ordering = ["-versao"]

    def __str__(self) -> str:
        status = " (ativo)" if self.ativo else ""
        return f"{self.nome} v{self.versao}{status}"

    def save(self, *args, **kwargs):
        """
        Override save para garantir que apenas um template esteja ativo.

        Se este template estiver sendo ativado, desativa todos os outros
        dentro de uma transação atômica.
        """
        if self.ativo:
            with transaction.atomic():
                # Desativa todos os outros templates
                PromptTemplate.objects.filter(ativo=True).exclude(
                    pk=self.pk
                ).update(ativo=False)
                super().save(*args, **kwargs)
        else:
            super().save(*args, **kwargs)
