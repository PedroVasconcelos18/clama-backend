"""
Management command para criar admin do Clama.
"""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

User = get_user_model()


class Command(BaseCommand):
    """
    Cria um usuário admin do Clama.

    Uso:
        python manage.py create_clama_admin --email admin@clama.com.br --password senhasegura

    O usuário será criado com:
    - is_clama_admin = True
    - is_staff = True (acesso ao Django admin)
    - is_superuser = False
    """

    help = "Cria um usuário admin do Clama"

    def add_arguments(self, parser):
        parser.add_argument(
            "--email",
            type=str,
            required=True,
            help="Email do admin",
        )
        parser.add_argument(
            "--password",
            type=str,
            required=True,
            help="Senha do admin",
        )
        parser.add_argument(
            "--nome",
            type=str,
            default="",
            help="Nome completo do admin (opcional)",
        )

    def handle(self, *args, **options):
        email = options["email"].lower().strip()
        password = options["password"]
        nome = options["nome"]

        # Verifica se já existe
        if User.objects.filter(email=email).exists():
            raise CommandError(f"Usuário com email {email} já existe.")

        # Cria o admin
        user = User.objects.create_user(
            email=email,
            password=password,
            nome_completo=nome,
            is_staff=True,  # Acesso ao Django admin
            is_superuser=False,  # Não é superusuário
            is_clama_admin=True,  # É admin do Clama
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"Admin criado com sucesso: {user.email}"
            )
        )
