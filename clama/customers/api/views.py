"""
Views da API customer-facing (`/api/customer/*`).

Endpoints:
- POST /api/customer/auth/login/             — Login customer (rejeita admin).
- POST /api/customer/auth/refresh/           — Renova access/refresh (rotação + blacklist).
- POST /api/customer/auth/logout/            — Idempotente, blacklist refresh.
- POST /api/customer/auth/change-password/   — Troca senha + zera flag.
- GET  /api/customer/me/                     — Retorna dados do user autenticado.

Permission `IsCustomerPasswordCurrent` em [clama/core/permissions.py](../../core/permissions.py)
é aplicada no `PedidoCreateView` (paywall G2.a). Aqui NÃO usamos em
`/me/` e `/change-password/` — user precisa poder ler seu próprio estado e
trocar senha mesmo com flag `force_change_password=True`.
"""

import logging

from django.contrib.auth import get_user_model
from django.db import transaction
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.generics import ListAPIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle, UserRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from clama.customers.api.serializers import (
    ChangePasswordSerializer,
    CustomerPedidoListSerializer,
    CustomerTokenObtainPairSerializer,
    CustomerUserSerializer,
)
from clama.orders.models import Pedido

logger = logging.getLogger("clama.customers.views")


class CustomerLoginThrottle(ScopedRateThrottle):
    """5/min por IP (configurado em settings.REST_FRAMEWORK.DEFAULT_THROTTLE_RATES)."""

    scope = "customer_login"


class ChangePasswordThrottle(UserRateThrottle):
    """
    10/hour por user. `UserRateThrottle` usa `request.user.pk` como ident
    quando autenticado, o que é exatamente o que queremos aqui — o
    endpoint exige `IsAuthenticated`.
    """

    scope = "customer_change_password"


class CustomerLoginView(TokenObtainPairView):
    """
    POST /api/customer/auth/login/

    Body: `{email, password}`.
    Response 200: `{access, refresh, user: {id, email, nome_completo,
    force_change_password, freemium_used_at}}`.
    Response 401: credenciais inválidas / admin rejeitado (mesma mensagem).
    """

    serializer_class = CustomerTokenObtainPairSerializer
    permission_classes = [AllowAny]
    throttle_classes = [CustomerLoginThrottle]
    throttle_scope = "customer_login"

    @extend_schema(
        tags=["Customer / Auth"],
        summary="Login customer",
    )
    def post(self, request, *args, **kwargs):
        return super().post(request, *args, **kwargs)


class CustomerRefreshView(TokenRefreshView):
    """
    POST /api/customer/auth/refresh/

    Reusa `TokenRefreshView` do simplejwt. Com
    `ROTATE_REFRESH_TOKENS=True` + `BLACKLIST_AFTER_ROTATION=True` (ambos
    em settings), rotaciona o refresh e blacklist o antigo.
    """

    permission_classes = [AllowAny]

    @extend_schema(
        tags=["Customer / Auth"],
        summary="Renovar tokens (rotação + blacklist)",
    )
    def post(self, request, *args, **kwargs):
        return super().post(request, *args, **kwargs)


class CustomerLogoutView(APIView):
    """
    POST /api/customer/auth/logout/

    Idempotente: 200 mesmo quando o refresh é vazio, inválido ou já
    blacklisted. Decisão deliberada — não revela ao atacante se ele já
    queimou o token (P-3 oracle de enumeração).
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Customer / Auth"],
        summary="Logout customer (idempotente)",
        responses={200: OpenApiResponse(description="OK (sempre)")},
    )
    def post(self, request, *args, **kwargs):
        refresh_str = (request.data.get("refresh") if hasattr(request, "data") else "") or ""
        if refresh_str:
            try:
                token = RefreshToken(refresh_str)
                token.blacklist()
            except (TokenError, Exception) as exc:
                # Logamos pra observar abuso mas não mudamos o response.
                logger.info(
                    "Logout customer com refresh inválido/expirado/blacklisted",
                    extra={
                        "event": "customer_logout_token_invalid",
                        "error": str(exc),
                    },
                )

        return Response({"detail": "ok"}, status=status.HTTP_200_OK)


class ChangePasswordView(APIView):
    """
    POST /api/customer/auth/change-password/

    Body: `{senha_atual, senha_nova}`.

    `transaction.atomic()` + `select_for_update` no User pra serializar
    troca concorrente e evitar update perdido. Em sucesso: aplica nova
    senha + zera `force_change_password`. Falha em qualquer ponto = rollback.
    """

    permission_classes = [IsAuthenticated]
    # IsCustomerPasswordCurrent NÃO é aplicada aqui — o endpoint precisa
    # estar acessível justamente pra resolver `force_change_password=True`.
    throttle_classes = [ChangePasswordThrottle]

    @extend_schema(
        tags=["Customer / Auth"],
        summary="Trocar senha do customer",
        request=ChangePasswordSerializer,
    )
    def post(self, request, *args, **kwargs):
        UserModel = get_user_model()

        with transaction.atomic():
            # `select_for_update` garante que outra request concorrente do
            # mesmo user (raro mas possível) não sobrescreva.
            user_locked = UserModel.objects.select_for_update().get(
                pk=request.user.pk
            )

            # Wrapper leve com .user apontando pro user locked. Evita mutar
            # `request.user` diretamente — a validação do serializer usa
            # esse user (ex.: `validate_senha_atual` confere `user.password`)
            # garantindo defesa TOCTOU se a senha mudou entre o JWT
            # decode e o lock.
            class _Ctx:
                pass

            ctx_request = _Ctx()
            ctx_request.user = user_locked
            ctx_request.data = request.data

            serializer = ChangePasswordSerializer(
                data=request.data, context={"request": ctx_request}
            )
            serializer.is_valid(raise_exception=True)

            user_locked.set_password(serializer.validated_data["nova_senha"])
            user_locked.force_change_password = False
            user_locked.save(update_fields=["password", "force_change_password"])

        return Response(
            {"detail": "Senha atualizada com sucesso."},
            status=status.HTTP_200_OK,
        )


class CustomerMeView(APIView):
    """
    GET /api/customer/me/

    Retorna dados do user autenticado. Sem `IsCustomerPasswordCurrent`
    (user precisa poder ler próprio estado mesmo com `force_change_password=True`).
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Customer"],
        summary="Dados do customer autenticado",
        responses={200: CustomerUserSerializer},
    )
    def get(self, request, *args, **kwargs):
        data = CustomerUserSerializer(request.user).data
        return Response(data, status=status.HTTP_200_OK)


class CustomerPedidosListView(ListAPIView):
    """
    GET /api/customer/pedidos/?from=YYYY-MM-DD&to=YYYY-MM-DD

    Lista pedidos do user autenticado, mais recentes primeiro.

    Filtros opcionais (query params):
      - `from` (ISO date) — pedidos criados em ou depois desta data.
      - `to`   (ISO date) — pedidos criados em ou antes desta data
        (inclusivo até 23:59:59 do dia informado).

    O isolamento entre users é garantido pelo filtro `user=request.user`
    no queryset — o `request.user` é resolvido pelo middleware JWT a
    partir do claim `user_id` no token assinado, então um user nunca
    consegue ver pedidos de outro (mesmo manipulando query params).

    Não exigimos `IsCustomerPasswordCurrent` aqui — listar pedidos é
    read-only e o user pode ler seu próprio estado mesmo com
    `force_change_password=True`. Faz parte da UX inicial.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = CustomerPedidoListSerializer

    def get_queryset(self):
        from datetime import date, datetime, time

        from django.utils import timezone

        qs = (
            Pedido.objects
            .filter(user=self.request.user)
            .select_related("plano")
            .order_by("-created_at")
        )

        from_raw = self.request.query_params.get("from") or ""
        to_raw = self.request.query_params.get("to") or ""

        # Datas inválidas são ignoradas silenciosamente — UX prefere lista
        # sem filtro a 400 hostil. Frontend já valida formato antes de
        # enviar (input type=date). `make_aware` aplica TIME_ZONE configurado
        # (America/Sao_Paulo) — "from=2026-01-15" significa 00:00 BRT, não UTC.
        try:
            if from_raw:
                d_from = date.fromisoformat(from_raw)
                qs = qs.filter(
                    created_at__gte=timezone.make_aware(
                        datetime.combine(d_from, time.min)
                    )
                )
        except ValueError:
            pass

        try:
            if to_raw:
                d_to = date.fromisoformat(to_raw)
                qs = qs.filter(
                    created_at__lte=timezone.make_aware(
                        datetime.combine(d_to, time.max)
                    )
                )
        except ValueError:
            pass

        return qs

    @extend_schema(
        tags=["Customer"],
        summary="Lista pedidos do customer autenticado",
        responses={200: CustomerPedidoListSerializer(many=True)},
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)
