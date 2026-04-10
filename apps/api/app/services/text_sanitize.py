"""PostgreSQL text/json 写入前清洗：去除 NUL 等会导致 psycopg 拒写的字符。"""

from __future__ import annotations

import hashlib
from typing import Any, TypeVar

T = TypeVar("T")


def sanitize_text_for_db(value: str | None) -> str:
    """去掉 \\x00（及 Unicode U+0000）；保留换行、空格及常规可见字符。"""
    if value is None:
        return ""
    if not value:
        return ""
    # 仅移除 NUL；不过度剥离其它 C0 控制符，以免误伤特殊排版
    return value.replace("\x00", "").replace("\u0000", "")


def sanitize_json_for_db(value: T) -> T:
    """递归清洗 dict/list/tuple 中所有字符串；其它类型原样返回。"""
    if value is None:
        return value
    if isinstance(value, str):
        return sanitize_text_for_db(value)  # type: ignore[return-value]
    if isinstance(value, dict):
        return {k: sanitize_json_for_db(v) for k, v in value.items()}  # type: ignore[return-value]
    if isinstance(value, list):
        return [sanitize_json_for_db(v) for v in value]  # type: ignore[return-value]
    if isinstance(value, tuple):
        return tuple(sanitize_json_for_db(v) for v in value)  # type: ignore[return-value]
    return value


def sanitize_chunk_spec_for_db(spec: dict[str, Any]) -> dict[str, Any]:
    """清洗即将写入 knowledge_chunks 的 rows_spec 单项（content / section_title / metadata_json）。"""
    out = dict(spec)
    out["content"] = sanitize_text_for_db(out.get("content"))
    st = out.get("section_title")
    out["section_title"] = sanitize_text_for_db(st) if st is not None else None
    if out["section_title"] is not None and len(out["section_title"]) > 200:
        out["section_title"] = out["section_title"][:200]
    mj = out.get("metadata_json")
    if mj is not None:
        out["metadata_json"] = sanitize_json_for_db(mj)
    meta = out.get("metadata_json")
    if isinstance(meta, dict) and out.get("content") and meta.get("content_hash"):
        meta = dict(meta)
        meta["content_hash"] = hashlib.sha256(out["content"].encode("utf-8")).hexdigest()
        out["metadata_json"] = meta
    return out


def sanitize_rows_spec_for_db(rows_spec: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [sanitize_chunk_spec_for_db(row) for row in rows_spec]
