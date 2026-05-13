from django.contrib import admin

from .models import Comentario, Post, Reacao


@admin.register(Post)
class PostAdmin(admin.ModelAdmin):
    list_display = ("titulo", "status", "data_publicacao", "autor", "updated_at")
    list_filter = ("status", "historia_ilustrativa")
    search_fields = ("titulo", "slug", "excerpt")
    readonly_fields = ("id", "created_at", "updated_at")
    prepopulated_fields = {"slug": ("titulo",)}
    ordering = ("-data_publicacao", "-created_at")
    date_hierarchy = "data_publicacao"
    fieldsets = (
        (
            "Identificação",
            {
                "fields": (
                    "id",
                    "titulo",
                    "slug",
                    "autor",
                    "historia_ilustrativa",
                )
            },
        ),
        (
            "Conteúdo",
            {
                "fields": (
                    "conteudo_html",
                    "conteudo_tiptap_json",
                    "excerpt",
                    "imagem_capa_url",
                )
            },
        ),
        (
            "SEO",
            {
                "fields": ("meta_title", "meta_description"),
                "classes": ("collapse",),
            },
        ),
        (
            "Publicação",
            {"fields": ("status", "data_publicacao")},
        ),
        (
            "Timestamps",
            {
                "fields": ("created_at", "updated_at"),
                "classes": ("collapse",),
            },
        ),
    )


@admin.register(Comentario)
class ComentarioAdmin(admin.ModelAdmin):
    list_display = ("customer", "post", "is_suspeito", "created_at")
    list_filter = ("is_suspeito",)
    search_fields = ("conteudo", "customer__email", "post__slug")
    readonly_fields = ("id", "ip_address", "created_at", "updated_at")
    ordering = ("-created_at",)
    date_hierarchy = "created_at"
    fieldsets = (
        ("Identificação", {"fields": ("id", "post", "customer")}),
        ("Conteúdo", {"fields": ("conteudo",)}),
        (
            "Moderação",
            {"fields": ("is_suspeito", "ip_address")},
        ),
        (
            "Timestamps",
            {
                "fields": ("created_at", "updated_at"),
                "classes": ("collapse",),
            },
        ),
    )


@admin.register(Reacao)
class ReacaoAdmin(admin.ModelAdmin):
    list_display = ("customer", "post", "tipo", "created_at")
    list_filter = ("tipo",)
    search_fields = ("customer__email", "post__slug")
    readonly_fields = ("id", "created_at", "updated_at")
    ordering = ("-created_at",)
