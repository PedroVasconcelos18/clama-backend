"""
Admin do app freemium.
"""

from django.contrib import admin

from clama.freemium.models import FreemiumBlacklist, FreemiumConfirmationToken


@admin.register(FreemiumBlacklist)
class FreemiumBlacklistAdmin(admin.ModelAdmin):
    """Admin para entradas da blacklist freemium."""

    list_display = ["created_at", "cpf_hash_curto", "email_hash_curto"]
    search_fields = ["cpf_hash", "email_hash"]
    readonly_fields = ["id", "created_at", "updated_at", "cpf_hash", "email_hash"]
    ordering = ["-created_at"]

    @admin.display(description="CPF (hash)")
    def cpf_hash_curto(self, obj: FreemiumBlacklist) -> str:
        return f"{obj.cpf_hash[:12]}…"

    @admin.display(description="E-mail (hash)")
    def email_hash_curto(self, obj: FreemiumBlacklist) -> str:
        return f"{obj.email_hash[:12]}…"


@admin.register(FreemiumConfirmationToken)
class FreemiumConfirmationTokenAdmin(admin.ModelAdmin):
    """Admin para tokens de confirmação por e-mail (double opt-in)."""

    list_display = ("token_truncado", "pedido", "created_at", "expires_at", "used_at")
    search_fields = ("pedido__id",)
    readonly_fields = (
        "id",
        "token",
        "pedido",
        "expires_at",
        "used_at",
        "ip_origem",
        "device_hash",
        "created_at",
        "updated_at",
    )
    ordering = ("-created_at",)

    @admin.display(description="Token")
    def token_truncado(self, obj: FreemiumConfirmationToken) -> str:
        return f"{obj.token[:8]}…"
