from django.apps import AppConfig


class UsersConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "clama_backend.users"
    verbose_name = "Users"

    def ready(self):
        # Importa signals (pre_save em User mantém email_hash/cpf_hash/
        # telefone_hash sincronizados com os campos plaintext).
        from . import signals  # noqa: F401
