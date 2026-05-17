"""
Serializers para a API customer-facing (`/api/customer/*`).

`CustomerTokenObtainPairSerializer` reusa `TokenObtainPairSerializer` do
simplejwt e adiciona:
- Lookup case-insensitive por email (alinha com F-17 do deferred-work).
- Rejeita admins do Clama com **mesma mensagem** de credenciais inválidas
  (sem oracle de role).
- Adiciona dados do user no response.

`ChangePasswordSerializer` valida senha atual, aplica
`AUTH_PASSWORD_VALIDATORS` na nova, e zera `force_change_password`.

`CustomerPedidoListSerializer` é o subset de campos do Pedido seguro pra
exibir no histórico `/me/pedidos/` — sem PII redundante.
"""

from django.contrib.auth import authenticate, get_user_model, password_validation
from django.contrib.auth.hashers import check_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from clama.core.exceptions import PastoralAPIException
from clama.core.pastoral_messages import (
    MSG_CUSTOMER_LOGIN_FALHOU,
)
from clama.orders.models import Pedido, PedidoStatus

User = get_user_model()


class CustomerLoginInvalidoError(PastoralAPIException):
    """401 — credenciais inválidas (email não existe, senha errada, ou admin)."""

    status_code = 401
    code = "customer_login_invalido"
    message = "Invalid credentials"
    pastoral_message = MSG_CUSTOMER_LOGIN_FALHOU


class CustomerUserSerializer(serializers.ModelSerializer):
    """Subset do User retornado por login/refresh/me.

    `nome_format_blog` é o único campo editável via PATCH /me/ (FR32 —
    customer escolhe entre 'completo' e 'compacto').

    `cpf_cnpj`/`telefone` são EncryptedCharField — o ModelSerializer não os
    auto-mapeia, então declaramos explícito (read-only, dado do próprio dono
    pra pré-preencher o form de pedido na /conta).
    """

    cpf_cnpj = serializers.SerializerMethodField()
    telefone = serializers.SerializerMethodField()

    def get_cpf_cnpj(self, obj: User) -> str:
        return obj.cpf_cnpj or ""

    def get_telefone(self, obj: User) -> str:
        return obj.telefone or ""

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "nome_completo",
            "force_change_password",
            "freemium_used_at",
            "nome_format_blog",
            # Dados de cadastro do próprio dono — usados pra pré-preencher o
            # form de novo pedido na /conta (self-service). Diferente do
            # serializer de PEDIDOS, que omite por ser contexto de listagem.
            "cpf_cnpj",
            "telefone",
            "idade",
            "sexo",
        ]
        # cpf_cnpj/telefone são SerializerMethodField (já read-only) — não
        # entram em read_only_fields (DRF rejeita).
        read_only_fields = [
            "id",
            "email",
            "nome_completo",
            "force_change_password",
            "freemium_used_at",
            "idade",
            "sexo",
        ]


class CustomerTokenObtainPairSerializer(TokenObtainPairSerializer):
    """
    Login de customer (não-admin).

    Comportamento:
    - Email lookup case-insensitive (`__iexact`).
    - Admin rejeitado com 401 idêntico (sem oracle de role: spec frozen).
    - Resposta inclui `user` ({id, email, nome_completo, force_change_password,
      freemium_used_at}).
    """

    username_field = "email"

    def validate(self, attrs):
        email = (attrs.get("email") or "").strip()
        password = attrs.get("password") or ""

        # Lookup case-insensitive antes do `authenticate`. Se não acharmos
        # um user (não-admin) com esse email, falha como credenciais
        # inválidas — sem distinguir email-inexistente de senha-errada.
        try:
            user = User.objects.get(email__iexact=email)
        except User.DoesNotExist:
            raise CustomerLoginInvalidoError()

        if not user.is_active:
            raise CustomerLoginInvalidoError()

        # Admin tentando logar via endpoint customer = 401 idêntico.
        if user.is_clama_admin:
            raise CustomerLoginInvalidoError()

        if not check_password(password, user.password):
            raise CustomerLoginInvalidoError()

        # Reusa o token-issuance do parent (gera access + refresh).
        # `authenticate` aqui apenas confirma o backend chain — passamos o
        # email exato do User (com case correto) e a senha original.
        authenticated = authenticate(
            request=self.context.get("request"),
            email=user.email,
            password=password,
        )
        if authenticated is None:
            # Defesa em profundidade — se o backend chain rejeitou por
            # algum motivo (custom auth, etc), trata como invalid.
            raise CustomerLoginInvalidoError()

        self.user = authenticated
        refresh = self.get_token(self.user)

        return {
            "access": str(refresh.access_token),
            "refresh": str(refresh),
            "user": CustomerUserSerializer(self.user).data,
        }


class ChangePasswordSerializer(serializers.Serializer):
    """
    Body do `POST /api/customer/auth/change-password/`.

    `senha_atual` confere com a senha atual do user (em modo
    `force_change_password=True`, é a temp gerada pela saga G1).
    `nova_senha` aplica `AUTH_PASSWORD_VALIDATORS`.

    Naming alinhado com o frontend (PT-BR natural: "nova senha", não "senha nova").
    """

    senha_atual = serializers.CharField(write_only=True, required=True)
    nova_senha = serializers.CharField(write_only=True, required=True)

    def validate_senha_atual(self, value):
        user = self.context["request"].user
        if not check_password(value, user.password):
            raise serializers.ValidationError(
                "Senha atual não confere."
            )
        return value

    def validate_nova_senha(self, value):
        user = self.context["request"].user
        try:
            password_validation.validate_password(value, user=user)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(list(exc.messages)) from exc
        return value


class ForgotPasswordSerializer(serializers.Serializer):
    """
    Body do `POST /api/customer/auth/forgot-password/`.

    Só valida o **formato** do e-mail. Deliberadamente NÃO verifica se o
    e-mail existe na base — a view responde sempre a mesma mensagem
    genérica (anti-enumeração de contas, ver
    `MSG_CUSTOMER_FORGOT_PASSWORD_ENVIADO`).
    """

    email = serializers.EmailField(required=True)

    def validate_email(self, value: str) -> str:
        # Normaliza pra lookup case-insensitive consistente com o login
        # (`User.objects.get(email__iexact=...)`).
        return value.strip()


class CustomerPedidoListSerializer(serializers.ModelSerializer):
    """
    Pedido do user no histórico da página `/conta`.

    Subset cuidadoso: NÃO retornamos cpf_cnpj, telefone, consent_ip,
    asaas_charge_id, device_hash. A `oracao_gerada` só vai quando o pedido
    está em `ENVIADA` — alinhado com a regra do `PedidoStatusSerializer`.
    """

    plano = serializers.CharField(source="plano.nome", read_only=True, default="")
    valor_reais_str = serializers.CharField(read_only=True)
    oracao_gerada = serializers.SerializerMethodField()

    class Meta:
        model = Pedido
        fields = [
            "id",
            "status",
            "plano",
            "valor_reais_str",
            "valor_centavos",
            "eh_gratuito",
            "canal_entrega",
            "created_at",
            "oracao_gerada",
        ]
        read_only_fields = fields

    def get_oracao_gerada(self, obj: Pedido) -> str | None:
        if obj.status == PedidoStatus.ENVIADA:
            return obj.oracao_gerada or None
        return None
