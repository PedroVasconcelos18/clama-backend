from django.apps import AppConfig


class OrdersConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "clama.orders"
    verbose_name = "Pedidos"

    def ready(self):
        """Registra signals quando o app é carregado."""
        from clama.orders import signals  # noqa: F401
