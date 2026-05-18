"""Converter Tiptap JSON (ProseMirror doc) → HTML pro blog.

Suporta apenas os nodes/marks usados no MVP. Nodes desconhecidos são
ignorados silenciosamente — bleach (em sanitization.py) é a defesa
final contra entradas inesperadas.

Texto é sempre HTML-escapado antes de entrar no template para evitar
injeção via payload de texto.
"""

from html import escape as _esc

_ALLOWED_HEADING_LEVELS = {2, 3}


def tiptap_json_to_html(json_doc: dict | None) -> str:
    """Converte um doc Tiptap (dict) para uma string HTML.

    Retorna "" se o input for None ou um dict vazio.
    """
    if not json_doc or not isinstance(json_doc, dict):
        return ""
    return _render_node(json_doc)


def _render_children(node: dict) -> str:
    return "".join(_render_node(child) for child in node.get("content", []))


def _render_node(node: dict) -> str:
    if not isinstance(node, dict):
        return ""
    node_type = node.get("type")
    handler = _NODE_HANDLERS.get(node_type)
    if handler is None:
        return ""
    return handler(node)


def _render_text(node: dict) -> str:
    text = node.get("text", "")
    if not text:
        return ""
    out = _esc(text)
    for mark in node.get("marks", []) or []:
        mark_type = mark.get("type")
        if mark_type == "bold":
            out = f"<strong>{out}</strong>"
        elif mark_type == "italic":
            out = f"<em>{out}</em>"
        elif mark_type == "link":
            attrs = mark.get("attrs", {}) or {}
            href = attrs.get("href", "")
            out = f'<a href="{_esc(href, quote=True)}">{out}</a>'
    return out


def _render_paragraph(node: dict) -> str:
    return f"<p>{_render_children(node)}</p>"


def _render_heading(node: dict) -> str:
    attrs = node.get("attrs", {}) or {}
    level = attrs.get("level")
    if level not in _ALLOWED_HEADING_LEVELS:
        return f"<p>{_render_children(node)}</p>"
    return f"<h{level}>{_render_children(node)}</h{level}>"


def _render_bullet_list(node: dict) -> str:
    return f"<ul>{_render_children(node)}</ul>"


def _render_ordered_list(node: dict) -> str:
    return f"<ol>{_render_children(node)}</ol>"


def _render_list_item(node: dict) -> str:
    return f"<li>{_render_children(node)}</li>"


def _render_blockquote(node: dict) -> str:
    return f"<blockquote>{_render_children(node)}</blockquote>"


def _render_horizontal_rule(_node: dict) -> str:
    return "<hr>"


def _render_hard_break(_node: dict) -> str:
    return "<br>"


def _render_image(node: dict) -> str:
    attrs = node.get("attrs", {}) or {}
    src = _esc(attrs.get("src") or "", quote=True)
    alt = _esc(attrs.get("alt") or "", quote=True)
    if not src:
        return ""
    return f'<img src="{src}" alt="{alt}">'


def _render_doc(node: dict) -> str:
    return _render_children(node)


_NODE_HANDLERS = {
    "doc": _render_doc,
    "paragraph": _render_paragraph,
    "heading": _render_heading,
    "bulletList": _render_bullet_list,
    "orderedList": _render_ordered_list,
    "listItem": _render_list_item,
    "blockquote": _render_blockquote,
    "horizontalRule": _render_horizontal_rule,
    "hardBreak": _render_hard_break,
    "image": _render_image,
    "text": _render_text,
}
