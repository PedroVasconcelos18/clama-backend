"""
Helpers para criptografar/descriptografar a senha temporária do fluxo
freemium enquanto ela está em trânsito pelo cache (Redis) entre a view que
cria o usuário e a task que envia o e-mail.

A chave é lida de `settings.FREEMIUM_TEMP_PWD_KEY` (Fernet — gerar com
`Fernet.generate_key()`). Veja `config/settings/base.py` para detalhes.

A `desencriptar_senha_do_cache` retorna string vazia em caso de falha de
decrypt (chave rotacionada, payload corrompido) — assim a task continua e
o e-mail é enviado sem o bloco de credenciais, mesmo fallback do "cache
expirou". Um warning vai pro Sentry para diagnóstico.
"""

import logging
import secrets

import sentry_sdk
from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings

logger = logging.getLogger("clama.freemium.temp_password")

# Charset da senha temporária — exclui caracteres ambíguos (0/O/o, I/l/1)
# para reduzir confusão quando a pessoa digita do e-mail. ~14 chars desse
# charset ≈ 80 bits de entropia. Espelha o ALPHABET_SENHA usado na saga
# freemium (`clama/freemium/api/views.py`); centralizado aqui para reuso
# pelo fluxo de recuperação de senha sem acoplar às views do freemium.
ALPHABET_SENHA_TEMP = (
    "ABCDEFGHJKLMNPQRSTUVWXYZ"
    "abcdefghijkmnpqrstuvwxyz"
    "23456789"
)


def gerar_senha_temporaria(tamanho: int = 14) -> str:
    """
    Gera senha temporária usando charset sem ambiguidade
    (sem 0/O/o/I/l/1). 14 chars ≈ 80 bits de entropia.
    """
    return "".join(secrets.choice(ALPHABET_SENHA_TEMP) for _ in range(tamanho))


def _fernet() -> Fernet:
    key = getattr(settings, "FREEMIUM_TEMP_PWD_KEY", "") or ""
    if isinstance(key, str):
        key = key.encode("utf-8")
    return Fernet(key)


def encriptar_senha_para_cache(senha: str) -> str:
    """
    Encripta a senha temporária para armazenamento em cache.

    Returns:
        String b64 (já é o output natural do Fernet).
    """
    if not senha:
        return ""
    token = _fernet().encrypt(senha.encode("utf-8"))
    return token.decode("utf-8")


def desencriptar_senha_do_cache(token: str) -> str:
    """
    Decripta a senha temporária lida do cache.

    Returns:
        Senha original em texto plano. Em falha (chave rotacionada,
        payload corrompido), retorna `""` e loga warning + Sentry.
    """
    if not token:
        return ""
    try:
        decrypted = _fernet().decrypt(token.encode("utf-8"))
    except InvalidToken as exc:
        logger.warning(
            "Falha ao decriptar senha temporária do freemium",
            extra={
                "event": "freemium_temp_pwd_decrypt_failed",
                "error": str(exc),
            },
        )
        sentry_sdk.capture_message(
            "Falha ao decriptar senha temporária do freemium (chave rotacionada?)",
            level="warning",
        )
        return ""
    return decrypted.decode("utf-8")
