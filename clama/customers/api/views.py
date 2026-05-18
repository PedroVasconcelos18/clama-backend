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

from clama.core.pastoral_messages import MSG_CUSTOMER_FORGOT_PASSWORD_ENVIADO
from clama.customers.api.serializers import (
    ChangePasswordSerializer,
    CustomerPedidoListSerializer,
    CustomerTokenObtainPairSerializer,
    CustomerUserSerializer,
    ForgotPasswordSerializer,
)
from clama.freemium.temp_password import gerar_senha_temporaria
from clama.notifications.services.email_sender import (
    enviar_email_recuperacao_senha,
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


class ForgotPasswordThrottle(ScopedRateThrottle):
    """
    3/hour por IP. Endpoint anônimo — `ScopedRateThrottle` cai pro ident
    de IP quando não há user autenticado, espelhando o `CustomerLoginThrottle`.
    Janela apertada para impedir email-bombing de uma vítima.
    """

    scope = "customer_forgot_password"


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


class ForgotPasswordView(APIView):
    """
    POST /api/customer/auth/forgot-password/

    Body: `{email}`.

    Fluxo "Esqueci minha senha":
      1. Valida o formato do e-mail (serializer).
      2. Procura um customer ATIVO e não-admin com esse e-mail
         (case-insensitive, mesmo lookup do login).
      3. Se achar: gera senha temporária, aplica via `set_password`,
         seta `force_change_password=True` (obriga troca no 1º acesso) e
         envia o e-mail **síncrono**.
      4. **Sempre** responde 200 com a mesma mensagem genérica
         (`MSG_CUSTOMER_FORGOT_PASSWORD_ENVIADO`) — não revela se o e-mail
         existe, é de admin ou está inativo (anti-enumeração de contas).

    Decisões (confirmadas com o produto):
    - **Síncrono**: sem Celery/cache. O envio acontece no request; não há o
      gargalo de geração de oração que justifica a fila no freemium.
    - **Reset de qualquer conta ativa**: funciona mesmo se a conta ainda
      estava com `force_change_password=True` (ex.: usuário freemium que
      perdeu o e-mail original com a senha temporária). A nova senha
      temporária simplesmente substitui a anterior.
    - **Anti-enumeração**: resposta idêntica em todos os casos. Falha de
      envio de e-mail é logada (Sentry via `@with_retry`) mas NÃO altera o
      response — não damos oracle de "esse e-mail existe mas o envio falhou".

    `transaction.atomic()` + `select_for_update` serializa requests
    concorrentes do mesmo user (raro, mas o throttle de 3/h já limita).
    """

    permission_classes = [AllowAny]
    throttle_classes = [ForgotPasswordThrottle]
    throttle_scope = "customer_forgot_password"

    @extend_schema(
        tags=["Customer / Auth"],
        summary="Solicitar recuperação de senha (envia senha temporária)",
        request=ForgotPasswordSerializer,
        responses={
            200: OpenApiResponse(
                description="Resposta genérica (sempre, anti-enumeração)"
            )
        },
    )
    def post(self, request, *args, **kwargs):
        serializer = ForgotPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"]

        UserModel = get_user_model()

        # Resposta genérica reutilizada em TODOS os caminhos de saída.
        generic_response = Response(
            {"detail": MSG_CUSTOMER_FORGOT_PASSWORD_ENVIADO},
            status=status.HTTP_200_OK,
        )

        try:
            with transaction.atomic():
                try:
                    user = (
                        UserModel.objects.select_for_update()
                        .get(email__iexact=email)
                    )
                except UserModel.DoesNotExist:
                    # E-mail não cadastrado — não revela. Log sem PII além
                    # do domínio (mesmo padrão do email_sender).
                    dominio = email.rsplit("@", 1)[-1] if "@" in email else "?"
                    logger.info(
                        "Forgot-password para e-mail não cadastrado",
                        extra={
                            "event": "customer_forgot_password_email_unknown",
                            "email_dominio": dominio,
                        },
                    )
                    return generic_response

                # Admin ou conta inativa: trata como se não existisse
                # (sem oracle de role/estado, igual ao login).
                if user.is_clama_admin or not user.is_active:
                    logger.info(
                        "Forgot-password ignorado (admin/inativo)",
                        extra={
                            "event": "customer_forgot_password_ignored",
                            "user_id": user.pk,
                            "is_admin": user.is_clama_admin,
                            "is_active": user.is_active,
                        },
                    )
                    return generic_response

                senha_temp = gerar_senha_temporaria()
                user.set_password(senha_temp)
                user.force_change_password = True
                user.save(
                    update_fields=["password", "force_change_password"]
                )

                primeiro_nome = (
                    user.nome_completo.split()[0]
                    if user.nome_completo
                    else "Amada"
                )

            # Envio FORA da transação — não seguramos o lock durante o I/O
            # de rede do SMTP. A senha já está persistida; se o e-mail
            # falhar, o `@with_retry` tenta 3x e o Sentry registra. A
            # resposta continua genérica (sem oracle de falha de envio).
            try:
                enviar_email_recuperacao_senha(
                    email_destino=user.email,
                    primeiro_nome=primeiro_nome,
                    senha_temporaria=senha_temp,
                )
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "Falha ao enviar e-mail de recuperação de senha",
                    extra={
                        "event": "customer_forgot_password_email_failed",
                        "user_id": user.pk,
                        "error": str(exc),
                    },
                )

            return generic_response

        except Exception as exc:  # noqa: BLE001
            # Defesa em profundidade: qualquer erro inesperado não pode
            # virar oracle de enumeração via status code diferente.
            logger.error(
                "Erro inesperado no forgot-password",
                extra={
                    "event": "customer_forgot_password_unexpected_error",
                    "error": str(exc),
                },
            )
            return generic_response


class CustomerMeView(APIView):
    """
    GET /api/customer/me/      — retorna dados do user autenticado.
    PATCH /api/customer/me/    — atualiza preferências editáveis pelo customer
                                 (apenas `nome_format_blog` no MVP; outros
                                 campos são read-only via whitelist do
                                 serializer).

    Sem `IsCustomerPasswordCurrent` (user precisa poder ler/editar próprio
    estado mesmo com `force_change_password=True`).
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

    @extend_schema(
        tags=["Customer"],
        summary="Atualiza preferências do customer (nome_format_blog)",
        request=CustomerUserSerializer,
        responses={200: CustomerUserSerializer},
    )
    def patch(self, request, *args, **kwargs):
        serializer = CustomerUserSerializer(
            instance=request.user, data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_200_OK)


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
