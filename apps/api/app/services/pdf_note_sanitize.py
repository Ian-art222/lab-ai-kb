"""文献笔记 JSON 中的 HTML 正文入库前清洗（防 XSS）。"""

from __future__ import annotations

import bleach

from app.services.text_sanitize import sanitize_json_for_db

_ALLOWED_TAGS = frozenset(
    {
        "p",
        "br",
        "strong",
        "b",
        "em",
        "i",
        "u",
        "s",
        "strike",
        "h1",
        "h2",
        "h3",
        "blockquote",
        "ul",
        "ol",
        "li",
        "a",
        "span",
        "div",
        "pre",
        "code",
    }
)
_ALLOWED_ATTRS = {
    "a": ["href", "title", "target", "rel"],
    "span": ["class"],
    "p": ["class"],
    "div": ["class"],
}


def sanitize_note_body_html(html: str | None) -> str:
    if not html or not isinstance(html, str):
        return ""
    cleaned = bleach.clean(
        html,
        tags=list(_ALLOWED_TAGS),
        attributes=_ALLOWED_ATTRS,
        strip=True,
    )
    return cleaned


def prepare_annotation_json_for_storage(raw: dict | None) -> dict:
    """清洗 JSON + 若含富文本字段则净化 HTML。"""
    data = sanitize_json_for_db(raw) if raw else {}
    if not isinstance(data, dict):
        data = {}
    else:
        data = dict(data)
    bh = data.get("body_html")
    if isinstance(bh, str) and bh.strip():
        data["body_html"] = sanitize_note_body_html(bh)
    return data
