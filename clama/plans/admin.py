"""
Admin do app plans.
"""
from django.contrib import admin

from .models import Plan


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = ("nome", "valor_centavos", "complexidade", "ordem", "ativo")
    list_filter = ("ativo", "complexidade")
    search_fields = ("nome",)
    ordering = ("ordem",)
