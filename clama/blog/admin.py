from django.contrib import admin

from .models import Post


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
