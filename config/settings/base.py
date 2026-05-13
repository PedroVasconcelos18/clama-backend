"""
Base settings for clama_backend project.

For more information on this file, see
https://docs.djangoproject.com/en/5.0/topics/settings/

For the full list of settings and their values, see
https://docs.djangoproject.com/en/5.0/ref/settings/
"""
import os
from pathlib import Path

import environ

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env()

# GENERAL
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#debug
DEBUG = env.bool("DJANGO_DEBUG", False)
# Flag explícita para detecção de contexto de teste (P-V3 wave 2).
# `config/settings/test.py` sobrescreve para True. Usado pelo
# `TurnstileClient` em vez da heurística frágil
# "test in sys.argv | pytest in sys.modules" (que ativava mock_mode em
# situações de produção: `--test-connection`, k8s probes, manifests test.yaml).
TESTING = False
# Local time zone. Choices are
# http://en.wikipedia.org/wiki/List_of_tz_zones_by_name
TIME_ZONE = "America/Sao_Paulo"
# https://docs.djangoproject.com/en/dev/ref/settings/#language-code
LANGUAGE_CODE = "pt-br"
# https://docs.djangoproject.com/en/dev/ref/settings/#site-id
SITE_ID = 1
# https://docs.djangoproject.com/en/dev/ref/settings/#use-i18n
USE_I18N = True
# https://docs.djangoproject.com/en/dev/ref/settings/#use-tz
USE_TZ = True
# https://docs.djangoproject.com/en/dev/ref/settings/#locale-paths
LOCALE_PATHS = [str(BASE_DIR / "locale")]

# DATABASES
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#databases
DATABASES = {
    "default": env.db(
        "DATABASE_URL",
        default="postgres://postgres:postgres@localhost:5432/clama_backend",
    ),
}
DATABASES["default"]["ATOMIC_REQUESTS"] = True
# https://docs.djangoproject.com/en/stable/ref/settings/#std:setting-DEFAULT_AUTO_FIELD
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# URLS
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#root-urlconf
ROOT_URLCONF = "config.urls"
# https://docs.djangoproject.com/en/dev/ref/settings/#wsgi-application
WSGI_APPLICATION = "config.wsgi.application"

# APPS
# ------------------------------------------------------------------------------
DJANGO_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.sites",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.admin",
    "django.forms",
    "django.contrib.sitemaps",
]
THIRD_PARTY_APPS = [
    "rest_framework",
    "rest_framework_simplejwt",
    # Necessário para `BLACKLIST_AFTER_ROTATION=True` ter efeito real e
    # para o `POST /api/customer/auth/logout/` revogar refresh tokens.
    # Sem este app + migrations rodadas, logout vira no-op silencioso.
    "rest_framework_simplejwt.token_blacklist",
    "drf_spectacular",
    "corsheaders",
    "anymail",
]
LOCAL_APPS = [
    "clama_backend.users",
    "clama.core",
    "clama.plans",
    "clama.orders",
    "clama.prompts",
    "clama.payments",
    "clama.prayer_generation",
    "clama.notifications",
    "clama.documents",
    "clama.freemium",
    "clama.customers",
    "clama.blog",
]
# https://docs.djangoproject.com/en/dev/ref/settings/#installed-apps
INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

# AUTHENTICATION
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#authentication-backends
AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
]
# https://docs.djangoproject.com/en/dev/ref/settings/#auth-user-model
AUTH_USER_MODEL = "users.User"
# https://docs.djangoproject.com/en/dev/ref/settings/#login-redirect-url
LOGIN_REDIRECT_URL = "/"
# https://docs.djangoproject.com/en/dev/ref/settings/#login-url
LOGIN_URL = "account_login"

# PASSWORDS
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#password-hashers
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher",
    "django.contrib.auth.hashers.BCryptSHA256PasswordHasher",
]
# https://docs.djangoproject.com/en/dev/ref/settings/#auth-password-validators
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"
    },
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# MIDDLEWARE
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#middleware
MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

# CORS
# ------------------------------------------------------------------------------
# https://github.com/adamchainz/django-cors-headers
CORS_ALLOWED_ORIGINS = env.list("DJANGO_CORS_ALLOWED_ORIGINS", default=[])

# STATIC
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#static-root
STATIC_ROOT = str(BASE_DIR / "staticfiles")
# https://docs.djangoproject.com/en/dev/ref/settings/#static-url
STATIC_URL = "/static/"
# https://docs.djangoproject.com/en/dev/ref/contrib/staticfiles/#std:setting-STATICFILES_DIRS
STATICFILES_DIRS = [str(BASE_DIR / "static")]
# https://docs.djangoproject.com/en/dev/ref/contrib/staticfiles/#staticfiles-finders
STATICFILES_FINDERS = [
    "django.contrib.staticfiles.finders.FileSystemFinder",
    "django.contrib.staticfiles.finders.AppDirectoriesFinder",
]

# MEDIA
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#media-root
MEDIA_ROOT = str(BASE_DIR / "media")
# https://docs.djangoproject.com/en/dev/ref/settings/#media-url
MEDIA_URL = "/media/"

# TEMPLATES
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#templates
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [str(BASE_DIR / "templates")],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.template.context_processors.i18n",
                "django.template.context_processors.media",
                "django.template.context_processors.static",
                "django.template.context_processors.tz",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# https://docs.djangoproject.com/en/dev/ref/settings/#form-renderer
FORM_RENDERER = "django.forms.renderers.TemplatesSetting"

# SECURITY
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#session-cookie-httponly
SESSION_COOKIE_HTTPONLY = True
# https://docs.djangoproject.com/en/dev/ref/settings/#csrf-cookie-httponly
CSRF_COOKIE_HTTPONLY = True
# https://docs.djangoproject.com/en/dev/ref/settings/#x-frame-options
X_FRAME_OPTIONS = "DENY"

# EMAIL
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#email-backend
EMAIL_BACKEND = env(
    "DJANGO_EMAIL_BACKEND",
    default="django.core.mail.backends.smtp.EmailBackend",
)
# https://docs.djangoproject.com/en/dev/ref/settings/#email-timeout
EMAIL_TIMEOUT = 5

# ADMIN
# ------------------------------------------------------------------------------
# Django Admin URL.
ADMIN_URL = "admin/"
# https://docs.djangoproject.com/en/dev/ref/settings/#admins
ADMINS = [("""Pedro Vasconcelos""", "pedro@clama.me")]
# https://docs.djangoproject.com/en/dev/ref/settings/#managers
MANAGERS = ADMINS

# LOGGING
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#logging
# See https://docs.djangoproject.com/en/dev/topics/logging for
# more details on how to customize your logging configuration.
#
# IMPORTANTE: NUNCA logar PII (dados pessoais identificáveis):
# - Nome completo da usuária
# - E-mail, telefone
# - Conteúdo do pedido de oração
# - Texto da oração gerada
# Logar apenas: pedido.id (UUID), plano.slug, status, timestamps, códigos de erro.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "%(levelname)s %(asctime)s %(module)s %(process)d %(thread)d %(message)s",
        },
        "json": {
            "()": "pythonjsonlogger.jsonlogger.JsonFormatter",
            "format": "%(asctime)s %(levelname)s %(name)s %(message)s",
        },
    },
    "handlers": {
        "console": {
            "level": "DEBUG",
            "class": "logging.StreamHandler",
            "formatter": "json",
        },
    },
    "root": {"level": "INFO", "handlers": ["console"]},
    "loggers": {
        "django.db.backends": {
            "level": "WARNING",
            "handlers": ["console"],
            "propagate": False,
        },
        "clama": {
            "level": "INFO",
            "handlers": ["console"],
            "propagate": False,
        },
    },
}

# SENTRY
# ------------------------------------------------------------------------------
# https://docs.sentry.io/platforms/python/guides/django/
SENTRY_DSN = env("SENTRY_DSN", default="")
if SENTRY_DSN:
    from clama.core.sentry_config import init_sentry

    init_sentry(
        dsn=SENTRY_DSN,
        environment=env("SENTRY_ENVIRONMENT", default="local"),
    )

# Celery
# ------------------------------------------------------------------------------
if USE_TZ:
    # https://docs.celeryq.dev/en/stable/userguide/configuration.html#std:setting-timezone
    CELERY_TIMEZONE = TIME_ZONE
# https://docs.celeryq.dev/en/stable/userguide/configuration.html#std:setting-broker_url
CELERY_BROKER_URL = env("CELERY_BROKER_URL", default="redis://localhost:6379/0")
# https://docs.celeryq.dev/en/stable/userguide/configuration.html#std:setting-result_backend
CELERY_RESULT_BACKEND = CELERY_BROKER_URL
# https://docs.celeryq.dev/en/stable/userguide/configuration.html#result-extended
CELERY_RESULT_EXTENDED = True
# https://docs.celeryq.dev/en/stable/userguide/configuration.html#std:setting-accept_content
CELERY_ACCEPT_CONTENT = ["json"]
# https://docs.celeryq.dev/en/stable/userguide/configuration.html#std:setting-task_serializer
CELERY_TASK_SERIALIZER = "json"
# https://docs.celeryq.dev/en/stable/userguide/configuration.html#std:setting-result_serializer
CELERY_RESULT_SERIALIZER = "json"
# https://docs.celeryq.dev/en/stable/userguide/configuration.html#task-time-limit
CELERY_TASK_TIME_LIMIT = 5 * 60
# https://docs.celeryq.dev/en/stable/userguide/configuration.html#task-soft-time-limit
CELERY_TASK_SOFT_TIME_LIMIT = 60
# https://docs.celeryq.dev/en/stable/userguide/configuration.html#beat-scheduler
CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"
# P-V9 wave 2: agendamento de reconciliação de Pedidos freemium órfãos
# (presos em AGUARDANDO_CONFIRMACAO_EMAIL por > 48h porque o e-mail de
# confirmação não foi entregue). Roda a cada 6h. O scheduler do
# django-celery-beat lê isso na primeira inicialização e cria
# `PeriodicTask` no banco; runs subsequentes podem ser editados via admin.
# Em ambientes onde `django_celery_beat` não estiver instalado/migrado, o
# Celery cai no scheduler default em memória, que também consome esta
# entrada.
from celery.schedules import crontab  # noqa: E402

CELERY_BEAT_SCHEDULE = {
    "freemium-reconciliar-orfaos": {
        "task": "clama.freemium.tasks.reconciliar_pedidos_freemium_orfaos",
        # A cada 6h, no minuto 17 (offset arbitrário pra não colidir com
        # outros beats potenciais). 24h também seria ok pelo padrão de
        # uso atual; preferimos 6h pra detectar problema mais cedo.
        "schedule": crontab(minute=17, hour="*/6"),
    },
}
# https://docs.celeryq.dev/en/stable/userguide/configuration.html#worker-send-task-events
CELERY_WORKER_SEND_TASK_EVENTS = True
# https://docs.celeryq.dev/en/stable/userguide/configuration.html#std-setting-task_send_sent_event
CELERY_TASK_SEND_SENT_EVENT = True

# django-rest-framework
# -------------------------------------------------------------------------------
# django-rest-framework - https://www.django-rest-framework.org/api-guide/settings/
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.AllowAny",),
    "DEFAULT_THROTTLE_CLASSES": ("rest_framework.throttling.AnonRateThrottle",),
    "DEFAULT_THROTTLE_RATES": {
        "anon": "60/min",
        "pedidos_create": "10/min",
        "pedidos_status": "60/min",
        "pedidos_checkout": "10/min",
        "admin_login": "5/min",
        # Freemium (pedido gratuito) — limite anti-fraude por IP.
        # Pós-renegociação 2026-05-08: o scope `freemium_otp` foi removido
        # (sem endpoint OTP) e `freemium_pedido` (5/min) foi substituído
        # por `freemium_pedido_ip` (5/h). Janela maior em vez de janela
        # estreita — defesa anti-fraude IP-level reforçada que vai junto
        # com CAPTCHA Turnstile + device fingerprint.
        "freemium_pedido_ip": "5/hour",
        # P-V13 wave 2: scope separado para `FreemiumConfirmarView`. Antes
        # reusava `freemium_pedido_ip` (5/h), o que cauterizava o IP do
        # usuário que tentava clicar várias vezes (mail scanner pre-fetch +
        # clique humano + retry > 5). Confirmar é mais barato — janela mais
        # generosa.
        "freemium_confirmar_ip": "30/hour",
        # Customer auth (G2.a backend, spec lp-user-existence-gate). Login
        # por IP (anti brute-force credenciais), change-password por user
        # (anti spray pós-takeover de sessão).
        "customer_login": "5/min",
        "customer_change_password": "10/hour",
    },
    "EXCEPTION_HANDLER": "clama.core.handlers.pastoral_exception_handler",
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}

# djangorestframework-simplejwt
# -------------------------------------------------------------------------------
# https://django-rest-framework-simplejwt.readthedocs.io/en/latest/settings.html
from datetime import timedelta

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(hours=24),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "AUTH_HEADER_TYPES": ("Bearer",),
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
}

# drf-spectacular
# -------------------------------------------------------------------------------
# https://drf-spectacular.readthedocs.io/en/latest/settings.html
from clama.core import __version__ as CLAMA_VERSION

SPECTACULAR_SETTINGS = {
    "TITLE": "Clama API",
    "DESCRIPTION": "API do Clama - Plataforma de oração pastoral personalizada",
    "VERSION": CLAMA_VERSION,
    "SERVE_INCLUDE_SCHEMA": False,
    # Evita colisões automáticas tipo "Status755Enum" quando múltiplos models
    # têm um campo `status` com choices distintas (ex.: PedidoStatus vs PostStatus).
    "ENUM_NAME_OVERRIDES": {
        "PedidoStatusEnum": "clama.orders.models.PedidoStatus.choices",
        "PostStatusEnum": "clama.blog.models.PostStatus.choices",
    },
}

# Encrypted Model Fields
# -------------------------------------------------------------------------------
# https://pypi.org/project/django-encrypted-model-fields/
# Chave Fernet para criptografia de dados sensíveis (LGPD)
# Gerar com: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
FIELD_ENCRYPTION_KEY = env(
    "FIELD_ENCRYPTION_KEY",
    default="",  # OBRIGATÓRIO em produção
)

# Asaas Payment Gateway
# -------------------------------------------------------------------------------
# https://docs.asaas.com/reference
# Note: Using os.environ.get directly because django-environ interprets $ as variable reference
ASAAS_API_KEY = os.environ.get("ASAAS_API_KEY", "")
ASAAS_BASE_URL = env(
    "ASAAS_BASE_URL",
    default="https://sandbox.asaas.com/api/v3",
)
# Valor mínimo da cobrança em centavos. A Asaas rejeita cobranças abaixo de
# R$5,00 (500 centavos) com "O valor da cobrança não pode ser menor que R$ 5,00"
# — limite global aplicado a qualquer billingType (PIX, boleto, cartão).
ASAAS_MIN_VALOR_CENTAVOS = env.int("ASAAS_MIN_VALOR_CENTAVOS", default=500)

# Frontend URL (for redirect callbacks)
# -------------------------------------------------------------------------------
FRONTEND_URL = env("FRONTEND_URL", default="http://localhost:5173")
# Alias usado pelo fluxo freemium (rota `/confirmado` no front).
# Usar a mesma origem se não foi customizado por env. Mantido como nome
# separado para permitir apontar pra subdominio/preview específico no
# futuro sem mexer no callback de pagamento.
FRONTEND_BASE_URL = env("FRONTEND_BASE_URL", default=FRONTEND_URL)

# Backend público — usado para montar links absolutos em e-mails (ex.: link
# de confirmação freemium aponta para `BACKEND_PUBLIC_URL/api/freemium/confirmar/`).
# Em local default aponta pro próprio backend Django.
BACKEND_PUBLIC_URL = env("BACKEND_PUBLIC_URL", default="http://localhost:8000")

# Blog (Story 2.12)
# -------------------------------------------------------------------------------
# Vercel Deploy Hook URL — chamada após publicar/despublicar/excluir post pra
# rebuildar o frontend SSG. Em local pode ficar vazio: task degrada como no-op
# com log warning.
VERCEL_DEPLOY_HOOK_URL = env("VERCEL_DEPLOY_HOOK_URL", default="")

# Chave IndexNow — usada pra notificar search engines de novos posts publicados.
# Best-effort: task ignora falhas (não dispara Sentry) e degrada como no-op se vazio.
INDEXNOW_KEY = env("INDEXNOW_KEY", default="")

# Base URL pública do blog (frontend SSG). Usada para montar URLs canônicas
# nos payloads de IndexNow.
FRONTEND_PUBLIC_BLOG_BASE_URL = env(
    "FRONTEND_PUBLIC_BLOG_BASE_URL",
    default="https://clama.me",
)

# Anthropic (Claude API)
# -------------------------------------------------------------------------------
# https://docs.anthropic.com/en/api
ANTHROPIC_API_KEY = env("ANTHROPIC_API_KEY", default="")

# Z-API (WhatsApp)
# -------------------------------------------------------------------------------
# https://developer.z-api.io/
ZAPI_INSTANCE_ID = env("ZAPI_INSTANCE_ID", default="")
ZAPI_TOKEN = env("ZAPI_TOKEN", default="")
ZAPI_BASE_URL = env("ZAPI_BASE_URL", default="https://api.z-api.io")

# Email (Resend via Anymail)
# -------------------------------------------------------------------------------
# https://anymail.dev/en/stable/esps/resend/
ANYMAIL = {
    "RESEND_API_KEY": env("RESEND_API_KEY", default=""),
}
DEFAULT_FROM_EMAIL = "Clama <oracao@clama.me>"

# Admin alert email for ERRO notifications
ADMIN_ALERT_EMAIL = env("ADMIN_ALERT_EMAIL", default="contato@clama.me")

# Freemium — flag para desabilitar despacho da task de geração em testes
# que querem somente verificar a saga sem efeitos colaterais externos.
FREEMIUM_DISPATCH_PRAYER_TASK = env.bool("FREEMIUM_DISPATCH_PRAYER_TASK", default=True)

# Freemium — chave HMAC usada para hashear os identificadores na
# `FreemiumBlacklist` (CPF, e-mail, telefone). Mantém os hashes determinísticos
# (necessário para lookup) mas inviabiliza ataque de dicionário cego sobre o
# banco. Em produção, defina `FREEMIUM_HASH_SECRET` via env como string aleatória
# de 32+ bytes (`python -c "import secrets; print(secrets.token_urlsafe(32))"`).
# Rotacionar invalida todos os hashes existentes — fazer apenas em emergência.
FREEMIUM_HASH_SECRET = env(
    "FREEMIUM_HASH_SECRET",
    default="dev-only-do-not-use-in-prod",
)

# Freemium — chave Fernet usada para criptografar a senha temporária do
# usuário no cache (Redis) entre a criação da conta e o envio do e-mail. Não
# precisa ser a mesma do `FIELD_ENCRYPTION_KEY`; idealmente é própria para
# permitir rotação independente. Gerar com:
#   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# Em produção, definir via env. O default é uma chave fixa de dev/test —
# se a chave não for válida, o decrypt cai num warning Sentry e o e-mail é
# enviado sem o bloco de credenciais (mesmo fallback do "cache expirou").
FREEMIUM_TEMP_PWD_KEY = env(
    "FREEMIUM_TEMP_PWD_KEY",
    default="xTEmld5LzkZz1xCiGvWLbeATZxQjTDx7z5SIRHRxbbg=",
)

# Anti-bypass por IP na FreemiumBlacklist — opção D (threshold de
# confirmações).
#
# A blacklist guarda 1 entry por confirmação. O check no submit conta
# quantas entries do mesmo IP existem dentro da `WINDOW_HOURS`. Bloqueia
# apenas se >= `THRESHOLD` (sinal forte de abuso). Permite uso legítimo
# em rede compartilhada (biblioteca, CGNAT móvel, escola, café) — até o
# THRESHOLD as primeiras pessoas conseguem.
#
# Atacante humano: cada confirmação exige clicar no link de email único,
# então acumular 3 confirmações no mesmo IP em 1h é um esforço grande
# (precisa de 3 mailboxes distintas). Atacante automatizado é parado
# antes pelo throttle de submissão (`freemium_pedido_ip=5/h`) +
# Turnstile + device_hash.
#
# Calibragem default conservadora (threshold=3 / window=1h):
#  - Biblioteca de 10 pessoas: 2 conseguem; 8 frustradas. Trade-off
#    explícito; admin pode aumentar threshold via env se virar dor.
#  - Atacante: 3+ confirmações sequenciais do mesmo IP/h bloqueia.
FREEMIUM_IP_BLACKLIST_WINDOW_HOURS = env.int(
    "FREEMIUM_IP_BLACKLIST_WINDOW_HOURS",
    default=1,
)
FREEMIUM_IP_BLACKLIST_THRESHOLD = env.int(
    "FREEMIUM_IP_BLACKLIST_THRESHOLD",
    default=3,
)

# Cloudflare Turnstile (CAPTCHA invisível — anti-fraude do fluxo freemium)
# -------------------------------------------------------------------------------
# https://developers.cloudflare.com/turnstile/
# Pós-renegociação 2026-05-08: Turnstile é a primeira camada anti-bot do
# Landing pública (antes do CPF / blacklist).
# - SECRET_KEY: usada server-side em `TurnstileClient.validate`. Default vazio
#   ativa o mock mode (dev/test). Em produção é obrigatório (P-1 anti-bypass:
#   `ImproperlyConfigured` em start-up se não-DEBUG e não-test).
# - SITE_KEY: pública, consumida pelo frontend (single-source-of-truth aqui).
# - VERIFY_URL: pode ser sobrescrito em testes para apontar para um stub.
TURNSTILE_SECRET_KEY = env("TURNSTILE_SECRET_KEY", default="")
TURNSTILE_SITE_KEY = env("TURNSTILE_SITE_KEY", default="")
TURNSTILE_VERIFY_URL = env(
    "TURNSTILE_VERIFY_URL",
    default="https://challenges.cloudflare.com/turnstile/v0/siteverify",
)
