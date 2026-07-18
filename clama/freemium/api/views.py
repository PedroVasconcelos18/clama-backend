"""
Views da API freemium (pós-renegociação 2026-05-08, hardening wave 2).

Endpoints:
- POST /api/freemium/pedidos/      — submete pedido gratuito (cria Pedido em
                                     AGUARDANDO_CONFIRMACAO_EMAIL e dispara
                                     e-mail com link de confirmação).
- GET /api/freemium/confirmar/?token=X — redireciona para a página
                                     intermediária do frontend (NÃO consome
                                     token; defende contra mail scanners
                                     que fazem pre-fetch de links).
- POST /api/freemium/confirmar/    — body `{token}`. Valida token e roda a
                                     saga atômica (User + blacklist + task
                                     `gerar_oracao_task`). Único caminho
                                     que de fato consome o token.

Pipeline anti-fraude da submissão (ordem):
  1. Throttle por IP (ScopedRateThrottle scope `freemium_pedido_ip`, 5/h).
  2. Deserializa request (algoritmo CPF/CNPJ + E.164 telefone vêm do serializer).
  3. CAPTCHA Cloudflare Turnstile (mock em dev/test).
  4. Disposable e-mail check.
  5. Cancela pedidos AGUARDANDO_CONFIRMACAO_EMAIL anteriores do mesmo CPF
     (P-V10 wave 2 — semântica "último submit ganha").
  6. Blacklist check (CPF + email — telefone ficou fora pós-renegociação).
  7. Atomic create do Pedido + token de confirmação + on_commit task de e-mail.

Hardening wave 2 (15 patches): vide spec change log
`docs/implementation-artifacts/spec-freemium-pedido-gratuito.md` seção
"Wave 2 — Hardening pós-review v2".
"""

import logging
import secrets

import requests
import sentry_sdk
from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.validators import validate_ipv46_address
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import HttpResponseRedirect
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from clama.core.exceptions import PastoralAPIException
from clama.core.legal import POLITICA_VERSAO_ATUAL
from clama.freemium.api.serializers import (
    FreemiumConfirmarResponseSerializer,
    PedidoFreemiumCreateRequestSerializer,
    PedidoFreemiumCreateResponseSerializer,
)
from clama.freemium.exceptions import (
    BlacklistHitError,
    ConfirmationTokenExpiradoError,
    ConfirmationTokenInvalidoError,
    EmailDescartavelError,
    PedidoEmAndamentoError,
    TurnstileInvalidoError,
    UserJaPossuiContaError,
)
from clama.freemium.hashing import (
    hash_cpf_cnpj,
    hash_email,
    hash_ip,
    hash_telefone,
    normalizar_email,
)
from clama.freemium.models import FreemiumBlacklist, FreemiumConfirmationToken
from clama.freemium.services import confirmation_service
from clama.freemium.services.email_blacklist import is_disposable
from clama.freemium.services.turnstile_client import TurnstileClient
from clama.freemium.temp_password import encriptar_senha_para_cache
from clama.orders.models import CanalEntrega, Pedido, PedidoStatus
from clama.plans.models import Complexidade, Plan
from clama.prayer_generation.tasks import gerar_oracao_task

logger = logging.getLogger("clama.freemium.views")

# Cache key onde a senha temporária (encriptada) do User criado fica
# disponível para a task de envio de e-mail. TTL = 24h para cobrir delays e
# retries do SMTP — o cleanup acontece após delivery confirmada (ver
# `notifications/tasks.py::_enviar_email_freemium`).
TEMP_PASSWORD_CACHE_PREFIX = "freemium:temp_password:"
TEMP_PASSWORD_TTL_SECONDS = 24 * 60 * 60

# Charset da senha temporária — exclui caracteres ambíguos (0/O/o, I/l/1)
# para reduzir confusão quando a usuária digita do email. ~14 chars desse
# charset = ~80 bits de entropia.
ALPHABET_SENHA = (
    "ABCDEFGHJKLMNPQRSTUVWXYZ"
    "abcdefghijkmnpqrstuvwxyz"
    "23456789"
)


def _key_temp_password(user_id) -> str:
    return f"{TEMP_PASSWORD_CACHE_PREFIX}{user_id}"


def _gerar_senha_temporaria() -> str:
    """
    Gera senha temporária de 14 caracteres usando charset sem ambiguidade
    (sem 0/O/o/I/l/1). ~80 bits de entropia.
    """
    return "".join(secrets.choice(ALPHABET_SENHA) for _ in range(14))


def _ip_request(request) -> str | None:
    """
    Extrai o IP do request com fallback X-Forwarded-For → REMOTE_ADDR.
    Retorna None se o IP for malformado (a coluna `Pedido.consent_ip` é
    nullable; aceitamos perder a informação em vez de estourar no save).
    """
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        ip = forwarded.split(",")[0].strip()
    else:
        ip = request.META.get("REMOTE_ADDR")

    if not ip:
        return None
    try:
        validate_ipv46_address(ip)
    except ValidationError:
        return None
    return ip


def _aplicar_headers_seguranca_confirmar(response):
    """
    Aplica headers de segurança no response do endpoint de confirmação:
    - `Referrer-Policy: no-referrer` (P-V7 wave 2): impede vazar o token
      via Referer header pra recursos third-party carregados pela página
      do frontend (analytics, fontes, etc).
    - `Cache-Control: no-store` (P-V18 wave 2): evita que proxies / CDNs
      cacheiem a resposta com o token na URL.
    """
    response["Referrer-Policy"] = "no-referrer"
    response["Cache-Control"] = "no-store"
    return response


def _get_plano_gratuito() -> Plan:
    """
    Retorna o `Plan` do fluxo freemium (complexidade SIMPLES_GRATUITA,
    invisível e ativo) — semeado pela migration `plans/0007`.

    Se a row sumir do banco (deploy parcial / rollback), levanta
    503 pastoral e dispara um sentry capture. Sem este guard, o
    `DoesNotExist` propaga como 500 sem mensagem amigável.
    """
    try:
        return Plan.objects.get(
            complexidade=Complexidade.SIMPLES_GRATUITA,
            visivel=False,
            ativo=True,
        )
    except Plan.DoesNotExist as exc:
        sentry_sdk.capture_message(
            "Plan freemium ausente do banco (SIMPLES_GRATUITA, visivel=False, ativo=True)",
            level="error",
        )
        raise PastoralAPIException(
            code="freemium_indisponivel",
            message="Plano freemium não configurado",
            pastoral_message=(
                "Estamos com problemas momentâneos. Tente em alguns minutos."
            ),
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        ) from exc


def _get_user_model():
    from django.contrib.auth import get_user_model

    return get_user_model()


class PedidoFreemiumCreateView(APIView):
    """
    POST /api/freemium/pedidos/

    Submissão do fluxo freemium (etapa 1 do double opt-in):
      1. Throttle por IP (5/h).
      2. Deserializa payload (Turnstile token, device_hash opcional, consent etc).
      3. Valida CAPTCHA Turnstile (PRIMEIRO, antes de qualquer chamada externa).
      4. Disposable e-mail check.
      5. Cancela pedidos AGUARDANDO_CONFIRMACAO_EMAIL anteriores do mesmo
         CPF (P-V10 — "último submit ganha", evita acúmulo de N órfãos).
      6. Blacklist check (CPF/email).
      7. Atomic create do Pedido em AGUARDANDO_CONFIRMACAO_EMAIL + token
         de confirmação + on_commit dispara `enviar_email_confirmacao_freemium_task`.
    """

    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "freemium_pedido_ip"

    @extend_schema(
        tags=["Freemium"],
        summary="Submeter pedido gratuito",
        request=PedidoFreemiumCreateRequestSerializer,
        responses={
            201: OpenApiResponse(response=PedidoFreemiumCreateResponseSerializer),
            400: OpenApiResponse(
                description="CAPTCHA inválido / e-mail descartável / dados inválidos"
            ),
            409: OpenApiResponse(description="CPF ou e-mail já usaram o pedido grátis"),
            429: OpenApiResponse(description="Rate limit por IP excedido (5/h)"),
        },
    )
    def post(self, request, *args, **kwargs):
        serializer = PedidoFreemiumCreateRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        nome = data["nome"].strip()
        email = normalizar_email(data["email"])
        telefone_e164 = data["telefone"]
        cpf_cnpj = data["cpf_cnpj"]
        idade = data.get("idade")
        sexo = data.get("sexo") or ""
        pedido_oracao_texto = (data.get("pedido_oracao") or "").strip()
        turnstile_token = data["turnstile_token"]
        # P-V15 wave 2: device_hash agora é opcional. Default vazio.
        device_hash = data.get("device_hash") or ""

        request_ip = _ip_request(request)

        # 1. CAPTCHA Turnstile primeiro — mata bots antes de qualquer trabalho.
        turnstile = TurnstileClient()
        try:
            captcha_ok = turnstile.validate(turnstile_token, ip=request_ip)
        except requests.RequestException as exc:
            sentry_sdk.capture_exception(exc)
            logger.error(
                "Falha permanente ao validar Turnstile",
                extra={"event": "turnstile_falha_permanente", "error": str(exc)},
            )
            raise TurnstileInvalidoError() from exc

        if not captcha_ok:
            raise TurnstileInvalidoError()

        # 2. Anti-disposable e-mail.
        if is_disposable(email):
            raise EmailDescartavelError()

        # 3a. User-existence gate (spec lp-user-existence-gate, 2026-05-10).
        # Antes do blacklist e do pedido-pendente, checa se algum
        # identificador (email plain, email_hash, cpf_hash, telefone_hash)
        # bate com User existente. Se sim → 409 com `redirect: "/login"`.
        #
        # Email plain entra na query alongside email_hash porque o gate
        # também precisa pegar Users criados antes do backfill (paranoia
        # extra — backfill já rodou em todos os ambientes, mas mantemos).
        cpf_hash_req = hash_cpf_cnpj(cpf_cnpj)
        email_hash_req = hash_email(email)
        telefone_hash_req = hash_telefone(telefone_e164)
        UserModel = _get_user_model()
        if UserModel.objects.filter(
            Q(email__iexact=email)
            | Q(email_hash=email_hash_req)
            | Q(cpf_hash=cpf_hash_req)
            | Q(telefone_hash=telefone_hash_req)
        ).exists():
            logger.info(
                "Submissão freemium bloqueada — user já tem conta (gate)",
                extra={"event": "freemium_user_existente_gate_hit"},
            )
            raise UserJaPossuiContaError()

        # 3b. Pedido pendente com mesmos identificadores. Substitui a
        # P-V10 (cancela e reusa) — agora bloqueia explicitamente. Itera
        # porque cpf_cnpj/email/telefone são EncryptedCharField (não dá
        # pra filtrar pelo cleartext direto).
        pedidos_pendentes_qs = Pedido.objects.filter(
            eh_gratuito=True,
            status=PedidoStatus.AGUARDANDO_CONFIRMACAO_EMAIL,
        )
        for p in pedidos_pendentes_qs:
            if (
                hash_cpf_cnpj(p.cpf_cnpj or "") == cpf_hash_req
                or hash_email(p.email or "") == email_hash_req
                or hash_telefone(p.telefone or "") == telefone_hash_req
            ):
                logger.info(
                    "Submissão freemium bloqueada — pedido pendente do mesmo identificador",
                    extra={
                        "event": "freemium_pedido_em_andamento_gate_hit",
                        "pedido_id": str(p.id),
                    },
                )
                raise PedidoEmAndamentoError()

        # 4. Blacklist check em camadas:
        #
        # a) Hashes "fortes" (CPF, email, telefone) — permanente. Sem janela,
        #    o registro vale enquanto o pedido existir.
        # b) `device_hash` — permanente também. Anti-bypass do mesmo browser.
        #    Skipped se vazio (FingerprintJS falhou: Brave/adblock).
        # c) `ip_hash` — janela de FREEMIUM_IP_BLACKLIST_WINDOW_HOURS (24h).
        #    Camada extra quando device_hash é instável (modo private). Não
        #    é permanente pra não cauterizar IPs residenciais a longo prazo
        #    (NAT, CGNAT).
        #
        # Cada camada é INDEPENDENTE — basta uma bater pra rejeitar.
        ip_hash_req = hash_ip(request_ip) if request_ip else ""
        permanent_q = (
            Q(cpf_hash=cpf_hash_req)
            | Q(email_hash=email_hash_req)
            | Q(telefone_hash=telefone_hash_req)
        )
        if device_hash:
            permanent_q |= Q(device_hash=device_hash)

        if FreemiumBlacklist.objects.filter(permanent_q).exists():
            logger.info(
                "Tentativa de submissão freemium com identificador já na blacklist",
                extra={
                    "event": "freemium_blacklist_hit_submit",
                    "layer": "permanent",
                },
            )
            raise BlacklistHitError()

        # IP check com janela temporal + threshold (opção D).
        #
        # Conta quantas confirmações anteriores existem do mesmo IP dentro
        # da janela. Bloqueia apenas se >= THRESHOLD — permite uso legítimo
        # em redes compartilhadas (biblioteca, CGNAT). Ver settings/base.py
        # pra calibragem.
        if ip_hash_req:
            from datetime import timedelta as _td

            window_hours = getattr(settings, "FREEMIUM_IP_BLACKLIST_WINDOW_HOURS", 1)
            threshold = getattr(settings, "FREEMIUM_IP_BLACKLIST_THRESHOLD", 3)
            window_start = timezone.now() - _td(hours=window_hours)
            ip_count = FreemiumBlacklist.objects.filter(
                ip_hash=ip_hash_req,
                created_at__gte=window_start,
            ).count()
            if ip_count >= threshold:
                logger.info(
                    "Submissão freemium bloqueada — IP atingiu threshold",
                    extra={
                        "event": "freemium_blacklist_hit_submit",
                        "layer": "ip_threshold",
                        "ip_count_in_window": ip_count,
                        "threshold": threshold,
                        "window_hours": window_hours,
                    },
                )
                raise BlacklistHitError()

        # 5. Saga de submissão atomic: cria novo Pedido + token + dispara
        # e-mail. A P-V10 (cancela pedido pendente) ficou obsoleta — agora
        # resubmissão com pedido pendente cai no PedidoEmAndamentoError
        # acima.
        consent_ip = request_ip
        plano_gratuito = _get_plano_gratuito()

        with transaction.atomic():

            pedido = Pedido.objects.create(
                nome=nome,
                email=email,
                telefone=telefone_e164,
                cpf_cnpj=cpf_cnpj,
                idade=idade,
                sexo=sexo,
                pedido_oracao=pedido_oracao_texto,
                plano=plano_gratuito,
                valor_centavos=0,
                eh_gratuito=True,
                canal_entrega=CanalEntrega.EMAIL,
                status=PedidoStatus.AGUARDANDO_CONFIRMACAO_EMAIL,
                consent_aceito=True,
                consent_versao=POLITICA_VERSAO_ATUAL,
                consent_aceito_at=timezone.now(),
                consent_ip=consent_ip,
                device_hash=device_hash,
            )

            token_str = confirmation_service.gerar_token(
                pedido,
                ip_origem=request_ip,
                device_hash=device_hash,
            )

            pedido_id_str = str(pedido.id)

            def _on_commit_dispatch_email():
                # Import lazy pra evitar ciclo (notifications.tasks importa
                # freemium nas operações de saga em outras tasks).
                from clama.notifications.tasks import (
                    enviar_email_confirmacao_freemium_task,
                )

                try:
                    enviar_email_confirmacao_freemium_task.delay(
                        pedido_id_str, token_str
                    )
                except Exception as exc:
                    sentry_sdk.capture_exception(exc)
                    logger.error(
                        "Falha ao enfileirar enviar_email_confirmacao_freemium_task",
                        extra={
                            "event": "freemium_enqueue_email_task_failed",
                            "pedido_id": pedido_id_str,
                            "error": str(exc),
                        },
                    )

            transaction.on_commit(_on_commit_dispatch_email)

        response_data = PedidoFreemiumCreateResponseSerializer(
            {
                "pedido_id": pedido.id,
                "status": PedidoStatus.AGUARDANDO_CONFIRMACAO_EMAIL,
            }
        ).data
        return Response(response_data, status=status.HTTP_201_CREATED)


class FreemiumConfirmarView(APIView):
    """
    GET / POST /api/freemium/confirmar/?token=X

    Etapa 2 do double opt-in. P-V2 wave 2 separa GET de POST:
    - GET → 302 redirect para `${FRONTEND_BASE_URL}/confirmar?token=X`
      onde o frontend mostra um botão "Confirmar minha oração". NÃO toca o
      token. Defende contra mail scanners (Safe Links, Mimecast, Proofpoint)
      que fazem GET pre-fetch nos links — antes da P-V2, o pre-fetch do
      scanner consumia o token e a usuária via "link já usado" ao clicar.
    - POST → executa a saga atômica (única forma de consumir o token).
      Body `{token}`. Retorna JSON 200 com `pedido_id` e `status`.

    Saga POST (em UM `transaction.atomic()` único — P-V1 wave 2):
      1. `confirmation_service.validar(token)` — `select_for_update`,
         valida não-expirado/não-usado, retorna Pedido.
      2. `select_for_update` no Pedido + assert status (P-V4).
      3. Re-check blacklist (defesa em profundidade).
      4. `User.objects.create_user`.
      5. `FreemiumBlacklist.create` (defesa real contra race; P-V6).
      6. `cache.set(senha_temp_encriptada)` (P-V6: só após blacklist OK).
      7. `Pedido.status = GERANDO_ORACAO + save`.
      8. `confirmation_service.marcar_usado(token)` (P-V1: só agora,
         dentro do atomic, e DEPOIS do sucesso da saga).
      9. `transaction.on_commit(dispatch task)`.

    Falha em qualquer ponto: `transaction.set_rollback(True)` + 4xx pastoral.
    Token volta a usável (cumpre frozen linha 30).
    """

    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    # P-V13 wave 2: scope dedicado, mais generoso (30/h vs 5/h da
    # submissão). Confirmar é mais barato pro backend e o mesmo IP pode
    # legitimamente clicar várias vezes (mail scanner pre-fetch, retry de
    # browser, refresh acidental).
    throttle_scope = "freemium_confirmar_ip"

    @extend_schema(
        tags=["Freemium"],
        summary="Redireciona para a página de confirmação no frontend",
        parameters=[
            OpenApiParameter(
                name="token",
                description="Token opaco enviado no e-mail de confirmação.",
                required=True,
                type=str,
            ),
        ],
        responses={
            302: OpenApiResponse(
                description=(
                    "Redirect para `${FRONTEND_BASE_URL}/confirmar?token=X`. "
                    "NÃO consome o token — apenas o POST executa a saga."
                )
            ),
        },
    )
    def get(self, request, *args, **kwargs):
        """
        P-V2 wave 2: GET sempre redireciona para o frontend. NÃO consome
        token. P-V12 wave 2: nunca retorna JSON (mesmo com Accept JSON) —
        comportamento previsível, sem heurística de Accept header.

        O token é simplesmente repassado na query string; se for vazio /
        inválido, o frontend mostra a mensagem pastoral apropriada quando
        o usuário tentar confirmar via POST.
        """
        token_str = (request.query_params.get("token") or "").strip()
        frontend_base = (
            getattr(settings, "FRONTEND_BASE_URL", "")
            or getattr(settings, "FRONTEND_URL", "")
            or "http://localhost:5173"
        ).rstrip("/")
        # Repassa o token só se não-vazio. Token inválido segue o mesmo
        # caminho — o frontend chama POST e recebe o erro pastoral.
        if token_str:
            redirect_url = (
                f"{frontend_base}/confirmar?token={token_str}"
            )
        else:
            redirect_url = f"{frontend_base}/confirmar"
        response = HttpResponseRedirect(redirect_url)
        return _aplicar_headers_seguranca_confirmar(response)

    @extend_schema(
        tags=["Freemium"],
        summary="Confirmar pedido gratuito (double opt-in) — executa saga",
        responses={
            200: OpenApiResponse(response=FreemiumConfirmarResponseSerializer),
            400: OpenApiResponse(description="Token inválido / expirado"),
            409: OpenApiResponse(
                description="Identificador entrou na blacklist entre o submit e a confirmação"
            ),
        },
    )
    def post(self, request, *args, **kwargs):
        token_str = (
            (request.data.get("token") if hasattr(request, "data") else None)
            or request.query_params.get("token")
            or ""
        ).strip()
        return self._handle_post(token_str)

    def _handle_post(self, token_str: str):
        """
        Executa validação + saga + marcar_usado em UMA transação atômica
        (P-V1 wave 2). Falha em qualquer ponto: `set_rollback(True)` para
        garantir que o outer transaction (ATOMIC_REQUESTS=True) também
        rolla back, evitando que o token fique consumido com saga
        incompleta.
        """
        try:
            with transaction.atomic():
                # 1. Valida token (select_for_update, sem marcar used_at).
                pedido = confirmation_service.validar(token_str)

                # 2. Saga atômica (cria User, blacklist, transita Pedido).
                pedido_id = self._executar_saga(pedido)

                # 3. Marca token como usado APÓS a saga ter sucesso. Se
                # qualquer passo da saga tiver levantado, não chegamos aqui.
                confirmation_service.marcar_usado(token_str)

                response_data = FreemiumConfirmarResponseSerializer(
                    {
                        "pedido_id": pedido_id,
                        "status": PedidoStatus.GERANDO_ORACAO,
                    }
                ).data
                response = Response(response_data, status=status.HTTP_200_OK)
                return _aplicar_headers_seguranca_confirmar(response)
        except (
            ConfirmationTokenInvalidoError,
            ConfirmationTokenExpiradoError,
            BlacklistHitError,
        ):
            # Garantia de rollback do outer (ATOMIC_REQUESTS). O atomic
            # interno já rollou ao propagar a exception, mas
            # `set_rollback(True)` é defesa em profundidade caso o handler
            # global mude no futuro.
            transaction.set_rollback(True)
            raise

    def _executar_saga(self, pedido: Pedido):
        """
        Cria User + blacklist + transita Pedido. Roda DENTRO do
        `transaction.atomic()` envolvente do `_handle_post` (P-V1 wave 2).

        Defesa em profundidade:
        - P-V4: select_for_update + precondition check no Pedido (race com
          admin/cleanup mid-saga).
        - Re-check de blacklist (alguém pode ter cadastrado mesmo CPF/email
          entre submit e confirmação).
        - P-V6: senha temp persistida no cache APÓS blacklist insert OK.

        Em colisão da blacklist OU do email do User, retorna 409 idêntico
        para não gerar oracle de enumeração.
        """
        UserModel = _get_user_model()
        senha_temp = _gerar_senha_temporaria()
        cpf_hash_req = hash_cpf_cnpj(pedido.cpf_cnpj)
        email_hash_req = hash_email(pedido.email)

        # P-V4 wave 2: select_for_update + precondition check. Bloqueia
        # qualquer mutação concorrente (admin, cleanup task) e garante que
        # o Pedido ainda está em AGUARDANDO_CONFIRMACAO_EMAIL. Se mudou
        # (ex.: cancelamento por resubmissão P-V10, manual ERRO), tratamos
        # como token inválido — coerente com a mensagem pastoral genérica.
        pedido_locked = (
            Pedido.objects.select_for_update().get(pk=pedido.pk)
        )
        if pedido_locked.status != PedidoStatus.AGUARDANDO_CONFIRMACAO_EMAIL:
            logger.info(
                "Confirmação freemium em pedido fora do estado esperado",
                extra={
                    "event": "freemium_confirm_estado_invalido",
                    "pedido_id": str(pedido_locked.id),
                    "status_atual": pedido_locked.status,
                },
            )
            raise ConfirmationTokenInvalidoError()
        pedido = pedido_locked  # usa a versão locked daqui em diante

        # Defesa em profundidade: re-check de blacklist. Race entre
        # dois fluxos diferentes (mesmo CPF passando submit em
        # paralelo) seria pego aqui. Inclui telefone_hash + device_hash
        # desde 2026-05-10.
        telefone_hash_req = hash_telefone(pedido.telefone or "")
        device_hash_req = pedido.device_hash or ""
        blacklist_q = (
            Q(cpf_hash=cpf_hash_req)
            | Q(email_hash=email_hash_req)
            | Q(telefone_hash=telefone_hash_req)
        )
        if device_hash_req:
            blacklist_q |= Q(device_hash=device_hash_req)
        if FreemiumBlacklist.objects.filter(blacklist_q).exists():
            logger.info(
                "Blacklist hit detectado durante confirmação freemium",
                extra={
                    "event": "freemium_blacklist_hit_confirm",
                    "pedido_id": str(pedido.id),
                },
            )
            raise BlacklistHitError()

        # Cria User. Colisão de email captura `IntegrityError` e
        # responde 409 igual à blacklist (evita oracle de enumeração: P-3).
        # `force_change_password=True` força troca da senha temporária no
        # primeiro login. `freemium_used_at` setado ANTES do
        # `marcar_usado` do token — fica em sync com a transição do Pedido.
        try:
            user = UserModel.objects.create_user(
                email=pedido.email,
                password=senha_temp,
                nome_completo=pedido.nome,
                cpf_cnpj=pedido.cpf_cnpj,
                telefone=pedido.telefone,
                # idade/sexo do Pedido pré-preenchem o form de pedido do
                # customer (SexoCadastro espelha Pedido.Sexo). Sem isto a
                # conta nascia com idade/sexo vazios mesmo o usuário tendo
                # informado no cadastro freemium.
                idade=pedido.idade,
                sexo=pedido.sexo,
                force_change_password=True,
                freemium_used_at=timezone.now(),
            )
        except IntegrityError as exc:
            logger.info(
                "Confirmação freemium colide com User existente",
                extra={
                    "event": "freemium_user_email_collision",
                    "pedido_id": str(pedido.id),
                    "error": str(exc),
                },
            )
            raise BlacklistHitError() from exc

        # Grava blacklist ANTES de tocar no cache (P-V6 wave 2): se o
        # blacklist insert falhar (race entre dois fluxos paralelos), a
        # transaction rolla back e o cache não fica com senha órfã 24h.
        # `telefone_hash` re-adicionado em 2026-05-10 (spec lp-user-existence-gate).
        # `device_hash` adicionado em 2026-05-10 (anti-bypass aba anônima).
        # `ip_hash` adicionado em 2026-05-11 (camada extra quando device_hash
        # é instável — Brave/Safari/incognito).
        try:
            FreemiumBlacklist.objects.create(
                cpf_hash=cpf_hash_req,
                email_hash=email_hash_req,
                telefone_hash=hash_telefone(pedido.telefone or ""),
                device_hash=(pedido.device_hash or None),
                ip_hash=(hash_ip(pedido.consent_ip) if pedido.consent_ip else None),
            )
        except IntegrityError as exc:
            logger.info(
                "Blacklist insert falhou durante confirmação (race)",
                extra={
                    "event": "freemium_blacklist_unique_collision_confirm",
                    "pedido_id": str(pedido.id),
                    "error": str(exc),
                },
            )
            raise BlacklistHitError() from exc

        # P-V6 wave 2: persiste senha temp encriptada no cache APÓS
        # blacklist insert success. Antes ficava entre `User.create` e
        # `Blacklist.create` — se Blacklist falhasse, o User era rollback
        # (Django) mas o cache ficava órfão por 24h, contendo plaintext
        # encriptado de uma senha pra um User que não existe mais.
        senha_cifrada = encriptar_senha_para_cache(senha_temp)
        cache.set(
            _key_temp_password(user.id),
            senha_cifrada,
            timeout=TEMP_PASSWORD_TTL_SECONDS,
        )

        # G2.a — marca o momento em que o User consumiu o pedido grátis.
        # Setado DENTRO do `transaction.atomic()` envolvente do `_handle_post`,
        # ANTES do `confirmation_service.marcar_usado(token)` (que ocorre logo
        # depois desta saga, no método chamador). Garante que o flag e o
        # consumo do token compartilham a mesma transação — falha posterior
        # (ex.: marcar_usado) rolla back ambos.
        #
        # P-12: NÃO sobrescreve `freemium_used_at` se já estiver setado.
        # Preserva a semântica "primeira vez que consumiu" (consistente com
        # o backfill da migration 0004). Cobre saga-replay + ainda permite
        # que o tick inicial seja registrado em qualquer ordem.
        if user.freemium_used_at is None:
            user.freemium_used_at = timezone.now()
            user.save(update_fields=["freemium_used_at"])

        # Vincula Pedido ao User e transita pra GERANDO_ORACAO.
        pedido.user = user
        pedido.status = PedidoStatus.GERANDO_ORACAO
        pedido.save(update_fields=["user", "status", "updated_at"])

        pedido_id_str = str(pedido.id)

        def _on_commit_dispatch_prayer_task():
            if not getattr(settings, "FREEMIUM_DISPATCH_PRAYER_TASK", True):
                return
            try:
                gerar_oracao_task.delay(pedido_id_str)
            except Exception as exc:
                sentry_sdk.capture_exception(exc)
                logger.error(
                    "Falha ao enfileirar gerar_oracao_task pós-confirmação",
                    extra={
                        "event": "freemium_enqueue_prayer_task_failed",
                        "pedido_id": pedido_id_str,
                        "error": str(exc),
                    },
                )

        transaction.on_commit(_on_commit_dispatch_prayer_task)

        return pedido.id
