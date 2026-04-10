"""
Custom managers para o app prompts.
"""

from django.db import models

from clama.core.exceptions import PastoralAPIException


class PromptTemplateManager(models.Manager):
    """Manager customizado para PromptTemplate."""

    def get_active(self):
        """
        Retorna o template de prompt ativo.

        Returns:
            PromptTemplate: O template ativo.

        Raises:
            PastoralAPIException: Se nenhum template ativo existir.
        """
        try:
            return self.get(ativo=True)
        except self.model.DoesNotExist:
            raise PastoralAPIException(
                code="no_active_prompt",
                message="Nenhum template de prompt ativo encontrado",
                pastoral_message="A oração precisa de um momento para se preparar.",
                status_code=500,
            )
