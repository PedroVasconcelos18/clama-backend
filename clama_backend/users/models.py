from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models
from encrypted_model_fields.fields import EncryptedCharField


class NomeFormatBlog(models.TextChoices):
    """Como o nome do customer aparece em comentários/likes do blog (FR32)."""

    COMPLETO = "completo", "Nome completo (Juliana Silva)"
    COMPACTO = "compacto", "Primeiro nome + inicial (Juliana S.)"


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

    # Formato do nome em comentários/likes do blog (FR32). Default compacto
    # é privacy-friendly: "Juliana S." em vez de "Juliana Silva" completo.
    nome_format_blog = models.CharField(
        "Formato do nome no blog",
        max_length=20,
        choices=NomeFormatBlog.choices,
        default=NomeFormatBlog.COMPACTO,
    )

    # Hashes determinísticos (HMAC-SHA-256 via FREEMIUM_HASH_SECRET) para
    # lookup do user-existence gate da Landing Page sem expor cleartext nem
    # depender de filter direto sobre EncryptedCharField (que não suporta).
    # Mantidos em sync via pre_save signal — bulk_create não dispara signals
    # e exige set manual.
    email_hash = models.CharField(
        max_length=64,
        db_index=True,
        verbose_name="Hash do e-mail",
        help_text="HMAC-SHA-256 do e-mail normalizado (Gmail canonical).",
    )
    cpf_hash = models.CharField(
        max_length=64,
        db_index=True,
        null=True,
        blank=True,
        verbose_name="Hash do CPF/CNPJ",
        help_text="HMAC-SHA-256 do CPF/CNPJ (somente dígitos).",
    )
    telefone_hash = models.CharField(
        max_length=64,
        db_index=True,
        null=True,
        blank=True,
        verbose_name="Hash do telefone",
        help_text="HMAC-SHA-256 do telefone (somente dígitos).",
    )

    # Marca o instante em que o usuário consumiu o pedido gratuito (saga G1).
    # Setado dentro de FreemiumConfirmarView._executar_saga ANTES do
    # marcar_usado do token. Indexed pra eventuais queries analíticas.
    freemium_used_at = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
        verbose_name="Pedido gratuito consumido em",
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
