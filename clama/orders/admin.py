"""
Admin para o app orders - Pedidos de oração.
"""

from django.contrib import admin

from clama.orders.models import Pedido


@admin.register(Pedido)
class PedidoAdmin(admin.ModelAdmin):
    """Admin para gestão de pedidos de oração."""

    list_display = (
        "created_at",
        "nome",
        "email",
        "plano",
        "valor_centavos",
        "status",
        "canal_entrega",
    )
    list_filter = ("status", "canal_entrega", "plano")
    search_fields = ("nome", "email")
    readonly_fields = (
        "id",
        "created_at",
        "updated_at",
        "asaas_charge_id",
        "asaas_invoice_url",
    )
    ordering = ("-created_at",)
    date_hierarchy = "created_at"

    fieldsets = (
        (
            "Identificação",
            {
                "fields": ("id", "created_at", "updated_at"),
            },
        ),
        (
            "Dados Pessoais",
            {
                "fields": ("nome", "email", "telefone", "idade", "sexo"),
            },
        ),
        (
            "Pedido",
            {
                "fields": ("pedido_oracao", "oracao_gerada"),
            },
        ),
        (
            "Plano e Pagamento",
            {
                "fields": (
                    "plano",
                    "valor_centavos",
                    "canal_entrega",
                    "status",
                ),
            },
        ),
        (
            "Integração Asaas",
            {
                "fields": ("asaas_charge_id", "asaas_invoice_url"),
                "classes": ("collapse",),
            },
        ),
    )
