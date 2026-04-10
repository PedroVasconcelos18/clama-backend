"""
Views da API de autenticação admin.
"""

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.throttling import ScopedRateThrottle
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from clama_backend.users.api.serializers import AdminTokenObtainPairSerializer


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
