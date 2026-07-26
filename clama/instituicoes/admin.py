"""
Admin do app instituicoes.
"""

from django.contrib import admin

from .models import Instituicao, Repasse


@admin.register(Instituicao)
class InstituicaoAdmin(admin.ModelAdmin):
    list_display = ("nome", "ordem", "ativo")
    list_filter = ("ativo",)
    search_fields = ("nome",)
    ordering = ("ordem", "nome")

    def has_delete_permission(self, request, obj=None) -> bool:
        # Soft-delete via campo `ativo`; hard-delete quebraria o histórico de repasses.
        return False


@admin.register(Repasse)
class RepasseAdmin(admin.ModelAdmin):
    list_display = (
        "pedido_ref",
        "instituicao",
        "valor_base_centavos",
        "percentual",
        "valor_centavos",
        "status",
        "created_at",
    )
    list_filter = ("status", "instituicao")
    list_select_related = ("instituicao",)
    search_fields = ("instituicao__nome",)
    ordering = ("-created_at",)
    readonly_fields = (
        "pedido_ref",
        "instituicao",
        "valor_base_centavos",
        "percentual",
        "valor_centavos",
        "status",
        "created_at",
        "updated_at",
    )

    @admin.display(description="Pedido")
    def pedido_ref(self, obj) -> str:
        # Exibe o id do pedido sem descriptografar PII (nome/email) via Pedido.__str__.
        return str(obj.pedido_id)

    def has_add_permission(self, request) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False
