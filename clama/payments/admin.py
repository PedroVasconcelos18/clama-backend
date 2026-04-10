from django.contrib import admin

from clama.payments.models import WebhookEvento


@admin.register(WebhookEvento)
class WebhookEventoAdmin(admin.ModelAdmin):
    """Admin para eventos de webhook."""

    list_display = [
        "created_at",
        "provider",
        "event_type",
        "status",
        "pedido",
        "external_event_id",
    ]
    list_filter = ["provider", "status", "event_type"]
    search_fields = ["external_event_id", "pedido__id"]
    readonly_fields = [
        "id",
        "created_at",
        "updated_at",
        "provider",
        "external_event_id",
        "event_type",
        "payload",
    ]
    ordering = ["-created_at"]

    fieldsets = [
        (
            "Identificação",
            {
                "fields": ["id", "provider", "external_event_id", "event_type"],
            },
        ),
        (
            "Status",
            {
                "fields": ["status", "pedido", "error_message"],
            },
        ),
        (
            "Payload",
            {
                "fields": ["payload"],
                "classes": ["collapse"],
            },
        ),
        (
            "Timestamps",
            {
                "fields": ["created_at", "updated_at"],
            },
        ),
    ]
