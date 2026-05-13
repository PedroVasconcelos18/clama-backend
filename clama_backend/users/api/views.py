"""
Views da API de autenticação admin e customer.
"""

from django.db import transaction
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.token_blacklist.models import (
    BlacklistedToken,
    OutstandingToken,
)
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from clama.core.exceptions import PastoralAPIException
from clama_backend.users.api.serializers import (
    AdminTokenObtainPairSerializer,
    CustomerChangePasswordSerializer,
    CustomerTokenObtainPairSerializer,
    CustomerUserSerializer,
)

# ---------------------------------------------------------------------------
# Admin
# ---------------------------------------------------------------------------


class AdminLoginView(TokenObtainPairView):
    """
    Autenticação de admin do Clama via JWT.

    Recebe email e senha, retorna access e refresh tokens
    junto com dados do usuário.

    Rate limit: 5 tentativas por minuto por IP.
    """

    serializer_class = AdminTokenObtainPairSerializer
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "admin_login"

    @extend_schema(
        tags=["Admin / Auth"],
        summary="Login de admin",
        description="""
Autentica um admin do Clama e retorna tokens JWT.

**Request:** `{email: str, password: str}`

**Response 200:** `{access: str, refresh: str, user: {id, email, nome_completo}}`

**Response 401:** Credenciais inválidas

**Response 403:** Usuário não é admin do Clama

**Rate limit:** 5 tentativas por minuto por IP
        """,
        responses={
            200: OpenApiResponse(description="Login bem-sucedido com tokens"),
            401: OpenApiResponse(description="Credenciais inválidas"),
            403: OpenApiResponse(description="Usuário não é admin"),
            429: OpenApiResponse(description="Rate limit excedido"),
        },
    )
    def post(self, request, *args, **kwargs):
        return super().post(request, *args, **kwargs)


class AdminTokenRefreshView(TokenRefreshView):
    """
    Renova access token usando refresh token.
    """

    @extend_schema(
        tags=["Admin / Auth"],
        summary="Renovar token",
        description="Renova o access token usando o refresh token.",
        responses={
            200: OpenApiResponse(description="Novo access token"),
            401: OpenApiResponse(description="Refresh token inválido ou expirado"),
        },
    )
    def post(self, request, *args, **kwargs):
        return super().post(request, *args, **kwargs)


# ---------------------------------------------------------------------------
# Customer (G2.a)
# ---------------------------------------------------------------------------


class CustomerLoginView(TokenObtainPairView):
    """
    Login customer (não-admin) via JWT.

    - Email/senha; case-insensitive no email.
    - Bloqueia usuários `is_clama_admin=True` com a mesma 401 genérica.
    - Rate limit: 5/min por IP (`customer_login`).
    """

    serializer_class = CustomerTokenObtainPairSerializer
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "customer_login"

    @extend_schema(
        tags=["Customer / Auth"],
        summary="Login do customer",
        description=(
            "Autentica um customer (não-admin) e retorna tokens JWT.\n\n"
            "Response 200: `{access, refresh, user{id, email, nome_completo, "
            "force_change_password, freemium_used_at}}`."
        ),
        responses={
            200: OpenApiResponse(description="Login bem-sucedido"),
            401: OpenApiResponse(description="Credenciais inválidas"),
            429: OpenApiResponse(description="Rate limit excedido"),
        },
    )
    def post(self, request, *args, **kwargs):
        return super().post(request, *args, **kwargs)


class CustomerTokenRefreshView(TokenRefreshView):
    """Renova access token customer usando refresh token."""

    @extend_schema(
        tags=["Customer / Auth"],
        summary="Renovar token (customer)",
        description="Renova o access token customer usando o refresh token.",
        responses={
            200: OpenApiResponse(description="Novo access token"),
            401: OpenApiResponse(description="Refresh token inválido ou expirado"),
        },
    )
    def post(self, request, *args, **kwargs):
        return super().post(request, *args, **kwargs)


class CustomerLogoutView(APIView):
    """
    Logout customer: revoga o refresh token via blacklist.

    Body: `{refresh: str}`. Sucesso retorna 205.

    Idempotência (P-1B): se o token já está blacklisted (ou inválido por
    outras razões "equivalentes a já gone" — expirado/malformado), seguimos
    retornando 205. O contrato do logout é "garantir que aquela sessão
    deixou de funcionar"; se já não funciona, o objetivo está cumprido.
    Frontend pode chamar logout múltiplas vezes (ex.: retry de rede)
    sem receber 401.

    O único caminho que ainda devolve 400 é o `refresh` ausente/vazio no
    body — isto é erro do CLIENTE, não estado do token. Cross-user spoof
    é tratado em P-4 logo abaixo (ainda dentro deste post).
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Customer / Auth"],
        summary="Logout do customer",
        description=(
            "Revoga o refresh token (`token_blacklist`) e retorna 205. "
            "Idempotente: chamadas com refresh já blacklisted/expirado também "
            "retornam 205 (o objetivo do logout — invalidar a sessão — já está "
            "cumprido). Apenas body sem `refresh` retorna 400."
        ),
        responses={
            205: OpenApiResponse(
                description=(
                    "Logout efetuado (refresh blacklisted) ou idempotente "
                    "(refresh já era inválido/blacklisted)"
                )
            ),
            400: OpenApiResponse(description="Body sem refresh ou refresh de outro usuário"),
        },
    )
    def post(self, request, *args, **kwargs):
        refresh_str = (request.data or {}).get("refresh")
        if not refresh_str:
            return Response(
                {
                    "error": {
                        "code": "refresh_required",
                        "message": "Refresh token is required",
                        "pastoral_message": "Não conseguimos efetuar o logout — refresh ausente.",
                    }
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        # P-1B: idempotência. Tentamos decodar e validar o ownership ANTES
        # de blacklistar. Se o token decoda mas é de outro user (P-4), 400
        # genérico. Se NÃO decoda (já blacklisted, expirado, malformado),
        # seguimos pra 205 — para o caller, o efeito é o mesmo: a sessão
        # ligada àquele refresh já não funciona.
        try:
            token = RefreshToken(refresh_str)
        except TokenError:
            # Token inválido ou já blacklisted — idempotente, retorna 205.
            return Response(status=status.HTTP_205_RESET_CONTENT)

        # P-4: confere que o refresh pertence ao usuário autenticado.
        # Mensagem genérica pra evitar info leak sobre o dono do token.
        token_user_id = token.payload.get("user_id")
        if token_user_id != request.user.pk:
            return Response(
                {
                    "error": {
                        "code": "refresh_invalid",
                        "message": "Refresh token does not belong to current session",
                        "pastoral_message": "Token inválido pra esta sessão.",
                    }
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            token.blacklist()
        except TokenError:
            # Race entre decode e blacklist (ex.: outra request blacklistou
            # entre a linha acima e esta). Mantém idempotência: 205.
            return Response(status=status.HTTP_205_RESET_CONTENT)
        return Response(status=status.HTTP_205_RESET_CONTENT)


class CustomerChangePasswordView(APIView):
    """
    Troca de senha do customer.

    NÃO usa `IsCustomerPasswordCurrent` — este é o caminho pra zerar a flag
    `force_change_password=True` setada pelo G1.

    Concorrência (frozen line: "atomic + select_for_update"): a operação roda
    dentro de `transaction.atomic()` e bloqueia a row do User com
    `select_for_update`. Garante que duas requisições paralelas não façam
    `set_password` em paralelo e gravem o hash de quem chegou primeiro,
    deixando o segundo "feliz" mas com a senha do primeiro.
    """

    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "customer_change_password"

    @extend_schema(
        tags=["Customer / Auth"],
        summary="Trocar senha (customer)",
        request=CustomerChangePasswordSerializer,
        description=(
            "Troca a senha do customer. Em modo force-change, aceita a "
            "senha temporária do G1 como `senha_atual`. Sucesso zera a "
            "flag `force_change_password`."
        ),
        responses={
            200: OpenApiResponse(description="Senha atualizada"),
            400: OpenApiResponse(description="Senha atual incorreta / nova inválida"),
            401: OpenApiResponse(description="Não autenticado"),
            429: OpenApiResponse(description="Rate limit excedido"),
        },
    )
    def post(self, request, *args, **kwargs):
        serializer = CustomerChangePasswordSerializer(
            data=request.data,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        senha_atual = serializer.validated_data["senha_atual"]
        nova_senha = serializer.validated_data["nova_senha"]

        UserModel = type(request.user)
        with transaction.atomic():
            # Bloqueia a row do User: garante atomicidade contra duas reqs
            # simultâneas mexendo no mesmo usuário (frozen — "atomic +
            # select_for_update").
            user = UserModel.objects.select_for_update().get(pk=request.user.pk)
            # P-3: TOCTOU fix — checa `senha_atual` AQUI, contra a row
            # freshly-locked do banco. Antes a validação rodava no
            # serializer contra o cache do JWT auth (request.user
            # carregado ANTES do lock); duas reqs concorrentes podiam
            # passar a checagem em paralelo e só serializar no WRITE.
            # Agora a checagem ocorre depois do `select_for_update`, então
            # apenas uma req lê o estado autoritativo por vez.
            if not user.check_password(senha_atual):
                raise PastoralAPIException(
                    code="senha_atual_invalida",
                    message="Current password mismatch",
                    pastoral_message="A senha atual está incorreta.",
                    status_code=400,
                )
            user.set_password(nova_senha)
            user.force_change_password = False
            user.save(update_fields=["password", "force_change_password"])

            # P-6: invalida TODAS as sessões refresh do user — dispositivos
            # antigos (e a própria sessão atual) precisam relogar.
            # Acesso atual dura até expirar (24h); refresh fica blacklisted
            # imediatamente, forçando re-login no próximo refresh.
            for outstanding in OutstandingToken.objects.filter(user_id=user.pk):
                BlacklistedToken.objects.get_or_create(token=outstanding)

        return Response(
            {
                "detail": "Senha atualizada com sucesso.",
                "pastoral_message": "Senha atualizada — você já pode seguir em paz.",
            },
            status=status.HTTP_200_OK,
        )


class CustomerMeView(APIView):
    """
    Retorna os dados do customer logado.

    NÃO usa `IsCustomerPasswordCurrent`: o frontend precisa ler a flag
    `force_change_password` para decidir o redirect (`/trocar-senha`),
    mesmo quando ela está ativa.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Customer / Auth"],
        summary="Meus dados (customer)",
        responses={
            200: OpenApiResponse(response=CustomerUserSerializer),
            401: OpenApiResponse(description="Não autenticado"),
        },
    )
    def get(self, request, *args, **kwargs):
        serializer = CustomerUserSerializer(request.user)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        tags=["Customer / Auth"],
        summary="Atualiza preferências do customer (nome_format_blog)",
        request=CustomerUserSerializer,
        responses={
            200: OpenApiResponse(response=CustomerUserSerializer),
            400: OpenApiResponse(description="Validação falhou"),
            401: OpenApiResponse(description="Não autenticado"),
        },
    )
    def patch(self, request, *args, **kwargs):
        """Atualiza preferências editáveis pelo customer.

        Whitelist via `read_only_fields` no serializer: apenas
        `nome_format_blog` é writable. Outros fields (email,
        nome_completo, etc.) são ignorados silenciosamente — não há
        edição parcial fora do escopo permitido.
        """
        serializer = CustomerUserSerializer(
            instance=request.user, data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_200_OK)
