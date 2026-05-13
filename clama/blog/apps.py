from django.apps import AppConfig


class BlogConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "clama.blog"
    verbose_name = "Blog"

    def ready(self) -> None:
        # Import dentro de ready() para evitar AppRegistryNotReady
        from . import signals  # noqa: F401
