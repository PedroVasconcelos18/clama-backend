from django.contrib import admin
from django.contrib.auth import admin as auth_admin
from django.contrib.auth import get_user_model

User = get_user_model()


@admin.register(User)
class UserAdmin(auth_admin.UserAdmin):
    """Admin para o modelo User customizado do Clama."""

    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Informações pessoais", {"fields": ("nome_completo", "name")}),
        (
            "Permissões",
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "is_clama_admin",
                    "groups",
                    "user_permissions",
                ),
            },
        ),
        ("Datas importantes", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("email", "password1", "password2", "is_clama_admin"),
            },
        ),
    )
    list_display = ["email", "nome_completo", "is_clama_admin", "is_active"]
    list_filter = ["is_clama_admin", "is_staff", "is_superuser", "is_active"]
    search_fields = ["nome_completo", "email"]
    ordering = ["email"]
