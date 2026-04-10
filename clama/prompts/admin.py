"""
Admin para o app prompts - Templates de prompt pastoral.
"""

from django.contrib import admin

from clama.prompts.models import PromptTemplate


@admin.register(PromptTemplate)
class PromptTemplateAdmin(admin.ModelAdmin):
    """Admin para gestão de templates de prompt."""

    list_display = ("nome", "versao", "ativo", "updated_at")
    list_filter = ("ativo",)
    search_fields = ("nome",)
    readonly_fields = ("id", "created_at", "updated_at")
    ordering = ("-versao",)
    actions = ["ativar_template"]

    fieldsets = (
        (
            "Identificação",
            {
                "fields": ("id", "nome", "versao", "ativo"),
            },
        ),
        (
            "Prompt",
            {
                "fields": ("system_prompt", "instrucoes_por_complexidade"),
            },
        ),
        (
            "Timestamps",
            {
                "fields": ("created_at", "updated_at"),
                "classes": ("collapse",),
            },
        ),
    )

    @admin.action(description="Ativar template selecionado")
    def ativar_template(self, request, queryset):
        """
        Ativa o(s) template(s) selecionado(s).

        Como apenas um pode estar ativo, ativar múltiplos resultará
        no último ser o ativo final.
        """
        count = 0
        for template in queryset:
            template.ativo = True
            template.save()
            count += 1

        self.message_user(
            request,
            f"{count} template(s) processado(s). Apenas o último está ativo.",
        )
