"""
Serializers para API de usuários/autenticação admin e customer.
"""

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

User = get_user_model()


# ---------------------------------------------------------------------------
# Admin
# ---------------------------------------------------------------------------


class AdminUserSerializer(serializers.ModelSerializer):
    """Serializer para dados do usuário admin."""

    class Meta:
        model = User
        fields = ["id", "email", "nome_completo"]
        read_only_fields = fields


class AdminTokenObtainPairSerializer(TokenObtainPairSerializer):
    """
    Serializer customizado para login admin.

    - Usa email como campo de login
    - Valida que o usuário é admin do Clama
    - Retorna dados do usuário junto com os tokens
    """

    username_field = "email"

    def validate(self, attrs):
        # Valida credenciais
        data = super().validate(attrs)

        # Verifica se é admin do Clama
        if not self.user.is_clama_admin:
            raise serializers.ValidationError(
                {
                    "error": {
                        "code": "not_admin",
                        "message": "User is not a Clama admin",
                        "pastoral_message": "Esse espaço é só para admins do Clama.",
                    }
                }
            )

        # Adiciona dados do usuário na resposta
        data["user"] = AdminUserSerializer(self.user).data

        return data


# ---------------------------------------------------------------------------
# Customer (G2.a)
# ---------------------------------------------------------------------------


class CustomerUserSerializer(serializers.ModelSerializer):
    """
    Serializer público dos dados do customer. Payload consumido por
    `/customer/auth/login/`, `/customer/me/` (GET + PATCH) e
    `/customer/auth/change-password/`.

    `nome_format_blog` é o único campo EDITÁVEL via PATCH /me/ (FR32 —
    customer escolhe entre 'completo'/'compacto' para o nome em
    comentários/likes do blog).
    """

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "nome_completo",
            "force_change_password",
            "freemium_used_at",
            "nome_format_blog",
        ]
        read_only_fields = [
            "id",
            "email",
            "nome_completo",
            "force_change_password",
            "freemium_used_at",
        ]


class CustomerTokenObtainPairSerializer(TokenObtainPairSerializer):
    """
    Login customer via JWT.

    - Usa email como campo de login (case-insensitive via `__iexact`).
    - Rejeita usuários `is_clama_admin=True` com a MESMA 401 genérica de
      credenciais inválidas — sem oracle de role.
    - Anexa `data['user'] = CustomerUserSerializer(self.user).data` no payload
      de sucesso.
    """

    username_field = "email"

    # Mensagem genérica reutilizada nos dois cenários ("credenciais erradas"
    # e "tentou logar como admin no endpoint customer"). Mantém o tom pastoral
    # e não revela qual dos dois aconteceu.
    INVALID_CREDENTIALS_ERROR = {
        "error": {
            "code": "invalid_credentials",
            "message": "Email or password invalid",
            "pastoral_message": "Email ou senha inválidos.",
        }
    }

    def validate(self, attrs):
        # Lookup case-insensitive de email — alinha com F-17 (deferred).
        # Antes de passar pra super().validate (que faz `authenticate()`),
        # tentamos resolver o email correto pelo `__iexact`. Se achar, normaliza
        # `attrs[email]` para o casing real do banco; se não, deixa o super
        # falhar com a 401 padrão.
        email_input = attrs.get(self.username_field, "") or ""
        if email_input:
            try:
                resolved = User.objects.get(email__iexact=email_input)
                attrs[self.username_field] = resolved.email
            except User.DoesNotExist:
                # Deixa o `super().validate()` lançar a 401 genérica do simplejwt.
                pass
            except User.MultipleObjectsReturned:
                # P-5: defesa em profundidade — `User.email` é `unique=True`
                # mas no Postgres a uniqueness é case-sensitive. Dois rows
                # `Foo@x.com` / `foo@x.com` poderiam coexistir antes de uma
                # normalização global (F-17 deferred). Sem este except,
                # `__iexact` levantaria `MultipleObjectsReturned` → 500.
                # Tratamos como "ambiguidade equivale a credenciais inválidas":
                # deixa o `super().validate()` falhar com a 401 genérica.
                pass

        # P-14: narrow except — `super().validate()` (TokenObtainPairSerializer)
        # falha com `AuthenticationFailed` para credenciais inválidas/conta
        # inativa. Capturamos APENAS isso e reembrulhamos com a mensagem
        # pastoral genérica. Outros erros (DB down, bug interno) devem
        # subir para o 500 normal — não silenciamos.
        from rest_framework.exceptions import AuthenticationFailed

        try:
            data = super().validate(attrs)
        except AuthenticationFailed as exc:
            raise AuthenticationFailed(self.INVALID_CREDENTIALS_ERROR) from exc

        # Bloqueia admins — sem revelar a role.
        if getattr(self.user, "is_clama_admin", False):
            from rest_framework.exceptions import AuthenticationFailed

            raise AuthenticationFailed(self.INVALID_CREDENTIALS_ERROR)

        data["user"] = CustomerUserSerializer(self.user).data
        return data


class CustomerChangePasswordSerializer(serializers.Serializer):
    """
    Troca de senha do customer.

    - `senha_atual`: write-only, presença obrigatória. A verificação real
      via `user.check_password()` foi movida para a VIEW, dentro do
      `transaction.atomic()` + `select_for_update()` da row do User
      (P-3 — fecha o TOCTOU em que a validação do serializer rodava
      contra o cache do JWT auth e duas requests concorrentes podiam
      passar a checagem antes da serialização do WRITE).
    - `nova_senha`: write-only, passa por `validate_password` do Django
      (validators padrão: mín. 8, não comum, não numérica, não similar
      ao email).
    """

    senha_atual = serializers.CharField(write_only=True, required=True)
    nova_senha = serializers.CharField(
        write_only=True,
        required=True,
        validators=[validate_password],
    )

    def validate_senha_atual(self, value):
        # P-3: validação de "está correta" foi MOVIDA pra view (atomic +
        # select_for_update). Aqui só reforça presença / não-vazio — o
        # `required=True` já barra omissão; mantemos um check explícito de
        # string vazia para mensagens consistentes.
        if not value:
            raise serializers.ValidationError("Senha atual é obrigatória.")
        return value
