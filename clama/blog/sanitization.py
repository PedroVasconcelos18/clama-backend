"""Sanitização HTML do blog — single source of truth pra whitelist.

Anti-pattern: chamar `bleach.clean()` direto fora deste módulo.
Sempre usar `sanitize_post_html()` — garante consistência da whitelist.
"""

import re

import bleach

# Pre-strip de tags onde o conteúdo textual também é perigoso ou ruidoso.
# bleach com strip=True remove apenas a tag, preservando o texto interno —
# para <script>alert(1)</script>, isso deixaria "alert(1)" como plaintext.
# Removemos o bloco inteiro antes de passar pro bleach.
_DANGEROUS_BLOCK_TAGS_RE = re.compile(
    r"<(?P<tag>script|style|iframe|embed|object|noscript|template)\b[^>]*>.*?</(?P=tag)>",
    flags=re.IGNORECASE | re.DOTALL,
)
# Variante self-closing / sem closing tag (defensiva).
_DANGEROUS_SELFCLOSE_RE = re.compile(
    r"<(script|style|iframe|embed|object|noscript|template)\b[^>]*/?>",
    flags=re.IGNORECASE,
)

BLOG_ALLOWED_TAGS = [
    "h2",
    "h3",
    "p",
    "strong",
    "em",
    "ul",
    "ol",
    "li",
    "blockquote",
    "a",
    "img",
    "br",
    "hr",
    "div",
]

BLOG_ALLOWED_ATTRIBUTES = {
    "a": ["href", "title", "rel"],
    "img": ["src", "alt", "title"],
    "div": ["class"],
    "blockquote": ["class"],
}

BLOG_ALLOWED_PROTOCOLS = ["http", "https"]


def sanitize_post_html(html: str) -> str:
    """Sanitiza HTML do blog usando a whitelist canônica.

    Duas camadas:
    1. Pre-strip de tags perigosas (script/style/iframe/...) incluindo conteúdo —
       evita resíduo cosmético tipo "alert(1)" em plaintext que bleach deixaria
       passar com strip=True.
    2. bleach.clean com whitelist — defesa principal contra XSS.

    Idempotente: chamadas repetidas retornam o mesmo resultado.
    """
    if not html:
        return ""
    cleaned = _DANGEROUS_BLOCK_TAGS_RE.sub("", html)
    cleaned = _DANGEROUS_SELFCLOSE_RE.sub("", cleaned)
    return bleach.clean(
        cleaned,
        tags=BLOG_ALLOWED_TAGS,
        attributes=BLOG_ALLOWED_ATTRIBUTES,
        protocols=BLOG_ALLOWED_PROTOCOLS,
        strip=True,
    )
