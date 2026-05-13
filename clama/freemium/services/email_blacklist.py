"""
Detecção de e-mails de provedores descartáveis (disposable).

Consulta uma lista estática (`clama.core.disposable_email_domains`).
Normaliza o input antes de comparar:
- lowercase + strip
- extrai domínio após o último '@'

A função é case-insensitive e tolerante a espaços em volta.
"""

from clama.core.disposable_email_domains import DISPOSABLE_EMAIL_DOMAINS


def _extrair_dominio(email: str) -> str | None:
    """Extrai o domínio (lowercase) do e-mail. Retorna None se inválido."""
    if not email:
        return None
    email_norm = email.strip().lower()
    if "@" not in email_norm:
        return None
    # Pega tudo após o último '@' (e-mails válidos têm exatamente um, mas
    # somos defensivos).
    dominio = email_norm.rsplit("@", 1)[1].strip()
    if not dominio:
        return None
    return dominio


def is_disposable(email: str) -> bool:
    """
    Retorna True se o e-mail pertence a um provedor descartável conhecido.

    Match por domínio E por qualquer ancestor (subdomínio):
    `mail.foo.mailinator.com` casa porque `mailinator.com` está na lista.
    Para o exact match `foo.com` na lista, `bar.foo.com` também casa.

    Args:
        email: e-mail a checar (qualquer caixa, com ou sem espaços).

    Returns:
        True se o domínio (ou um ancestor) está na lista de descartáveis.
        False para inputs inválidos / domínios legítimos. A validação de
        formato é feita pelo serializer DRF antes.
    """
    dominio = _extrair_dominio(email)
    if dominio is None:
        return False
    # Exact match + ancestor match — ex.: para "mail.foo.mailinator.com",
    # checamos "mail.foo.mailinator.com", "foo.mailinator.com" e
    # "mailinator.com" (paramos no primeiro hit). Não testamos o TLD sozinho
    # (ex.: "com") porque a lista nunca tem TLDs nus.
    partes = dominio.split(".")
    for i in range(len(partes) - 1):
        candidato = ".".join(partes[i:])
        if candidato in DISPOSABLE_EMAIL_DOMAINS:
            return True
    return False
