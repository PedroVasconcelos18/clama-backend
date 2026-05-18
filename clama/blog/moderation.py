"""Moderação automática de comentários — detecta termos suspeitos.

A função `eh_comentario_suspeito` é chamada via signal `pre_save` em
`Comentario` (vide `signals.py`) para setar `is_suspeito` automaticamente.

Lista pode crescer; em Growth, considerar IA via Claude API pra detectar
padrões mais sutis (ironia, dog-whistles, etc.).
"""

import re
import unicodedata

# Lista inicial — pragmaticamente escolhida: termos óbvios pt-BR + spam
# patterns comuns. False positives são moderação manual extra (admin pode
# desflagar deletando o comentário); preferimos não censurar agressivamente.
BLOG_PALAVRAS_SUSPEITAS: frozenset[str] = frozenset(
    [
        # Xingamentos comuns pt-BR
        "buceta",
        "caralho",
        "porra",
        "merda",
        "cuzao",
        "vagabundo",
        "vagabunda",
        "fdp",
        "puta",
        "putinha",
        "puto",
        "filhodaputa",
        "filhadaputa",
        "cu",
        "viado",
        "bicha",
        "babaca",
        "otario",
        "otaria",
        "idiota",
        "imbecil",
        # Termos depreciativos a denominações / hate speech
        "satanico",
        "satanica",
        "blasfemia",
        "herege",
        "demonio",
        # Spam patterns (CTA agressivo, golpe)
        "compre agora",
        "curso gratis",
        "curso grátis",
        "ganhe dinheiro",
        "ganhe agora",
        "click aqui",
        "clique aqui",
        "investimento garantido",
        "renda extra",
        "trabalhe em casa",
    ]
)


_WORD_RE = re.compile(r"[a-zà-ÿ0-9]+", re.IGNORECASE)


def _normalizar(texto: str) -> str:
    """Lowercase + remove acentos (NFD strip combining marks)."""
    if not texto:
        return ""
    nfd = unicodedata.normalize("NFD", texto.lower())
    return "".join(ch for ch in nfd if unicodedata.category(ch) != "Mn")


def eh_comentario_suspeito(conteudo: str) -> bool:
    """Retorna True se o conteúdo contém termo de `BLOG_PALAVRAS_SUSPEITAS`.

    Normaliza (lowercase + remove acentos) e tokeniza por word boundary
    pra evitar match de substring dentro de palavra legítima.

    Para entradas de spam pattern (multi-palavra como "compre agora"),
    procuramos a sequência no texto normalizado.
    """
    if not conteudo:
        return False
    normalizado = _normalizar(conteudo)
    # Single-word match via tokens (word boundary)
    tokens = set(_WORD_RE.findall(normalizado))
    for termo in BLOG_PALAVRAS_SUSPEITAS:
        termo_norm = _normalizar(termo)
        if " " in termo_norm:
            # Multi-word: busca por substring (depois de normalização)
            if termo_norm in normalizado:
                return True
        else:
            if termo_norm in tokens:
                return True
    return False
