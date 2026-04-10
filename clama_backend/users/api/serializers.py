"""
Serializers para API de usuários/autenticação admin.
"""

from django.contrib.auth import get_user_model
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

User = get_user_model()


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
