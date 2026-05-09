from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models
from encrypted_model_fields.fields import EncryptedCharField


class UserManager(BaseUserManager):
    """
    Manager customizado para User com métodos de conveniência.
    """

    use_in_migrations = True

    def _create_user(self, email, password, **extra_fields):
        """Cria e salva um User com email e senha."""
        if not email:
            raise ValueError("Email é obrigatório")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        """Cria usuário comum."""
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password=None, **extra_fields):
        """Cria superusuário."""
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_clama_admin", True)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")

        return self._create_user(email, password, **extra_fields)

    def clama_admins(self):
        """Retorna queryset de admins do Clama ativos."""
        return self.filter(is_clama_admin=True, is_active=True)


class User(AbstractUser):
    """
    Custom user model for Clama.

    Usa email como identificador único ao invés de username.
    Inclui flag is_clama_admin para controle de acesso ao painel admin.
    """

    # Remove username, usa email como identificador
    username = None  # type: ignore[assignment]
    email = models.EmailField("E-mail", unique=True)

    # Nome completo
    nome_completo = models.CharField(
        "Nome completo",
        max_length=120,
        blank=True,
        default="",
    )

    # Legacy field - alias para compatibilidade
    name = models.CharField("Nome", blank=True, max_length=255)
    first_name = None  # type: ignore[assignment]
    last_name = None  # type: ignore[assignment]

    # Flag de admin do Clama
    is_clama_admin = models.BooleanField(
        "Admin do Clama",
        default=False,
        help_text="Designa se o usuário pode acessar o painel admin do Clama.",
    )

    # Dados pessoais para fluxo freemium / customer (criptografados, LGPD)
    cpf_cnpj = EncryptedCharField(
        max_length=20,
        null=True,
        blank=True,
        verbose_name="CPF/CNPJ",
    )
    telefone = EncryptedCharField(
        max_length=20,
        null=True,
        blank=True,
        verbose_name="Telefone",
    )

    # Sinaliza que o usuário precisa trocar a senha temporária no próximo login.
    # Usado pelo fluxo freemium ao criar conta com senha gerada automaticamente.
    force_change_password = models.BooleanField(
        "Forçar troca de senha",
        default=False,
        help_text="Indica que o usuário deve trocar a senha no próximo login.",
    )

    # Marca o momento em que o usuário consumiu o pedido grátis (saga freemium).
    # Setado dentro da `transaction.atomic()` da `FreemiumConfirmarView._executar_saga`
    # antes do `marcar_usado` do token. Indexado para permitir queries
    # analíticas e segmentação anti-fraude futura.
    freemium_used_at = models.DateTimeField(
        "Usou freemium em",
        null=True,
        blank=True,
        db_index=True,
    )

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    class Meta:
        verbose_name = "Usuário"
        verbose_name_plural = "Usuários"

    def get_full_name(self) -> str:
        return self.nome_completo or self.name or self.email

    def get_short_name(self) -> str:
        return self.nome_completo.split()[0] if self.nome_completo else self.email
