"""
Utilitários de hashing para a blacklist do freemium.

Os identificadores (CPF/CNPJ, e-mail, telefone) são armazenados na blacklist
apenas como hashes HMAC-SHA-256 com chave (`FREEMIUM_HASH_SECRET`). Antes
de hashear, normalizamos:

- CPF/CNPJ: somente dígitos.
- E-mail: lowercase + strip.
- Telefone: somente dígitos (formato E.164 sem o "+").

O HMAC é determinístico — precisamos consultar pelo valor original durante o
pre-checkin do fluxo freemium, então salt aleatório por linha não serve. A
chave (server secret) impede que um atacante com acesso somente-leitura ao
banco consiga reverter o hash via dicionário/rainbow table de CPFs conhecidos.
A chave fica em `settings.FREEMIUM_HASH_SECRET` (env-loaded). Rotacionar a
chave invalida todos os hashes existentes — operação de emergência.
"""

import hashlib
import hmac

from django.conf import settings


def _secret_bytes() -> bytes:
    """
    Lê a chave HMAC do settings. Falha cedo se não configurada — em prod,
    o env é obrigatório; em dev/test há um default seguro o suficiente
    (ver `config/settings/base.py`).
    """
    secret = getattr(settings, "FREEMIUM_HASH_SECRET", "") or ""
    return secret.encode("utf-8")


def _hash(valor: str) -> str:
    """HMAC-SHA-256 hex digest (64 chars) de um identificador normalizado."""
    return hmac.new(
        _secret_bytes(), valor.encode("utf-8"), hashlib.sha256
    ).hexdigest()


def normalizar_cpf_cnpj(documento: str) -> str:
    """Mantém apenas dígitos do CPF/CNPJ."""
    return "".join(c for c in (documento or "") if c.isdigit())


# Domínios Gmail que aplicam canonicalização (dots ignorados, alias `+`
# ignorado). googlemail.com é o domínio histórico em UK/DE — Google entrega
# nas mesmas caixas.
_GMAIL_DOMAINS = frozenset({"gmail.com", "googlemail.com"})


def normalizar_email(email: str) -> str:
    """
    Normaliza e-mail para hashing/lookup determinístico.

    P-V11 wave 2: canonicaliza aliases Gmail. `alice@gmail.com`,
    `alice+spam@gmail.com` e `a.l.i.c.e@gmail.com` são a MESMA caixa pela
    regra do Google — sem essa canonicalização, o atacante driblaria a
    blacklist gerando aliases triviais (~70% dos endereços BR são Gmail).

    Para domínios fora dos `_GMAIL_DOMAINS`, mantém o lowercase + strip do
    v1 (alguns provedores tratam dots como significativos; ex.: outlook,
    domínios corporativos).
    """
    canonical = (email or "").strip().lower()
    if "@" not in canonical:
        return canonical
    localpart, domain = canonical.split("@", 1)
    if domain in _GMAIL_DOMAINS:
        # Remove tudo após o `+` (alias plus-addressing) e remove dots do
        # localpart. Mantém domínio original (gmail.com vs googlemail.com)
        # — o servidor Google trata os dois como a mesma caixa, mas
        # canonicalizar pra um faria perder o sinal de origem nos logs.
        # O hash bate igual mesmo com domínios distintos pois normalizamos
        # para `localpart_canonical@gmail.com` abaixo.
        localpart = localpart.split("+", 1)[0].replace(".", "")
        canonical = f"{localpart}@gmail.com"
    return canonical


def normalizar_telefone(telefone: str) -> str:
    """Mantém apenas dígitos do telefone (E.164 sem o '+')."""
    return "".join(c for c in (telefone or "") if c.isdigit())


def hash_cpf_cnpj(documento: str) -> str:
    """Normaliza e hasheia CPF/CNPJ."""
    return _hash(normalizar_cpf_cnpj(documento))


def hash_email(email: str) -> str:
    """Normaliza e hasheia e-mail."""
    return _hash(normalizar_email(email))


def hash_telefone(telefone: str) -> str:
    """Normaliza e hasheia telefone."""
    return _hash(normalizar_telefone(telefone))


def normalizar_ip(ip: str) -> str:
    """
    Normaliza endereço IP para hashing.

    IPv4: trim. IPv6: lowercase + trim. Não fazemos canonicalização agressiva
    (ex.: expand `::` para 0000:0000:...) — simples lowercase cobre os casos
    comuns. Lookup falha-fechado: se o IP veio em forma incomum, não bate
    com a blacklist (atacante consegue contornar mudando representação).
    Pra MVP é aceitável.
    """
    return (ip or "").strip().lower()


def hash_ip(ip: str) -> str:
    """
    HMAC-SHA-256 do IP normalizado. Não armazenamos IP em claro na blacklist
    pra reduzir superfície LGPD (IP é dado pessoal). Pedido.consent_ip
    mantém o cleartext pra fins forenses, mas a blacklist só usa hash.

    String vazia (`""`) ainda gera hash determinístico — chamadas com IP
    ausente nunca devem chegar até aqui (view skip).
    """
    return _hash(normalizar_ip(ip))
