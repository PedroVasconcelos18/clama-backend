"""
Test settings for clama_backend project.
"""
from .base import *  # noqa
from .base import env

# GENERAL
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#secret-key
SECRET_KEY = env(
    "DJANGO_SECRET_KEY",
    default="test-secret-key-do-not-use-in-production",
)
# https://docs.djangoproject.com/en/dev/ref/settings/#test-runner
TEST_RUNNER = "django.test.runner.DiscoverRunner"

# Sinaliza explicitamente o contexto de teste (P-V3 wave 2). Substitui a
# heurística frágil em `_is_testing` do TurnstileClient.
TESTING = True

# PASSWORDS
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#password-hashers
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# EMAIL
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#email-backend
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

# DEBUGGING FOR TEMPLATES
# ------------------------------------------------------------------------------
TEMPLATES[0]["OPTIONS"]["debug"] = True  # type: ignore[index] # noqa: F405

# Your stuff...
# ------------------------------------------------------------------------------

# THROTTLING
# ------------------------------------------------------------------------------
# Desabilita throttling em testes para não atrapalhar a suíte
REST_FRAMEWORK["DEFAULT_THROTTLE_CLASSES"] = []  # type: ignore[name-defined] # noqa: F405

# CACHE
# ------------------------------------------------------------------------------
# Cache local em memória para testes (em produção: Redis).
CACHES = {  # noqa: F405
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "clama-tests",
    }
}

# CELERY
# ------------------------------------------------------------------------------
# Em testes, executa tasks no thread atual (síncrono) — facilita asserts
# sobre side-effects sem precisar de worker rodando.
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
