"""
结构感知切块管道（v3）：block → parent 单元 → child 切片，配合 metadata 与可配置目标长度。
中文场景用「字符 + 近似 token」启发式，避免强依赖 tiktoken。
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.core.config import settings as app_settings


PIPELINE_VERSION = "v3_structural"
# 文本抽取规则版本（与切块 pipeline 解耦，供 diagnostics 展示）
EXTRACTOR_RULES_VERSION = "extract_v2_rules"


def approx_tokens(text: str) -> int:
    """中英混合近似 token：汉字加权，ASCII 词粗略按词界。"""
    if not text:
        return 0
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    rest = len(text) - cjk
    # CJK ~1 char ≈ 1 token; ASCII ~4 chars ≈ 1 token
    return max(1, cjk + max(1, rest // 4))


def approx_chars_for_tokens(tokens: int) -> int:
    """从目标 token 反推字符预算（中文偏置）。"""
    return max(80, int(tokens * 1.15))


@dataclass
class RawBlock:
    text: str
    block_type: str
    heading_path: list[str] = field(default_factory=list)
    section_title: str | None = None
    page_number: int | None = None
    source_type: str = "text"


def sanitize_raw_block(b: RawBlock) -> RawBlock:
    from app.services.text_sanitize import sanitize_text_for_db

    return RawBlock(
        text=sanitize_text_for_db(b.text),
        block_type=b.block_type,
        heading_path=[sanitize_text_for_db(h) for h in (b.heading_path or [])],
        section_title=sanitize_text_for_db(b.section_title) if b.section_title else None,
        page_number=b.page_number,
        source_type=b.source_type,
    )


def _heading_path_str(path: list[str]) -> str:
    return " > ".join(p for p in path if p) if path else ""


# --- Markdown ---

def parse_markdown_blocks(text: str) -> list[RawBlock]:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    blocks: list[RawBlock] = []
    heading_stack: list[tuple[int, str]] = []
    buf: list[str] = []
    in_code = False
    code_lang = ""

    def current_path() -> list[str]:
        return [t for _, t in heading_stack]

    def current_title() -> str | None:
        return heading_stack[-1][1] if heading_stack else None

    def flush_paragraph() -> None:
        body = "\n".join(buf).strip()
        buf.clear()
        if not body:
            return
        bt = "code" if body.startswith("```") else _classify_text_block(body)
        blocks.append(
            RawBlock(
                text=body,
                block_type=bt,
                heading_path=list(current_path()),
                section_title=current_title(),
                page_number=None,
                source_type="markdown",
            )
        )

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if stripped.startswith("```"):
            if in_code:
                buf.append(line)
                flush_paragraph()
                in_code = False
                i += 1
                continue
            flush_paragraph()
            in_code = True
            buf.append(line)
            i += 1
            continue

        if in_code:
            buf.append(line)
            i += 1
            continue

        if stripped.startswith("#"):
            flush_paragraph()
            level = len(stripped) - len(stripped.lstrip("#"))
            title = stripped[level:].strip() or None
            while heading_stack and heading_stack[-1][0] >= level:
                heading_stack.pop()
            if title:
                heading_stack.append((level, title))
            i += 1
            continue

        if stripped.startswith("|") or (stripped and "|" in stripped and stripped.count("|") >= 2):
            flush_paragraph()
            tbl_lines = [line]
            i += 1
            while i < len(lines):
                s2 = lines[i].strip()
                if not s2:
                    break
                if s2.startswith("|") or ("|" in s2 and s2.count("|") >= 2):
                    tbl_lines.append(lines[i])
                    i += 1
                else:
                    break
            t = "\n".join(tbl_lines).strip()
            if t:
                blocks.append(
                    RawBlock(
                        text=t,
                        block_type="table",
                        heading_path=list(current_path()),
                        section_title=current_title(),
                        page_number=None,
                        source_type="markdown",
                    )
                )
            continue

        if _is_list_line(stripped):
            flush_paragraph()
            lst = [line]
            i += 1
            while i < len(lines):
                s2 = lines[i].strip()
                if not s2:
                    break
                if _is_list_line(s2) or (s2.startswith("  ") and lst):
                    lst.append(lines[i])
                    i += 1
                else:
                    break
            lt = "\n".join(lst).strip()
            if lt:
                blocks.append(
                    RawBlock(
                        text=lt,
                        block_type="list",
                        heading_path=list(current_path()),
                        section_title=current_title(),
                        page_number=None,
                        source_type="markdown",
                    )
                )
            continue

        if _looks_like_faq_start(stripped):
            flush_paragraph()
            faq_lines = [line]
            i += 1
            while i < len(lines):
                s2 = lines[i].strip()
                if not s2:
                    faq_lines.append("")
                    i += 1
                    continue
                if _looks_like_faq_answer_start(s2) or _looks_like_faq_start(s2):
                    break
                faq_lines.append(lines[i])
                i += 1
            if i < len(lines) and _looks_like_faq_answer_start(lines[i].strip()):
                faq_lines.append(lines[i])
                i += 1
                while i < len(lines):
                    s2 = lines[i].strip()
                    if not s2:
                        faq_lines.append("")
                        i += 1
                        continue
                    if _looks_like_faq_start(s2):
                        break
                    faq_lines.append(lines[i])
                    i += 1
            ft = "\n".join(faq_lines).strip()
            if ft:
                blocks.append(
                    RawBlock(
                        text=ft,
                        block_type="faq_pair",
                        heading_path=list(current_path()),
                        section_title=current_title(),
                        page_number=None,
                        source_type="markdown",
                    )
                )
            continue

        buf.append(line)
        i += 1

    flush_paragraph()
    return [b for b in blocks if b.text.strip()]


def _is_list_line(s: str) -> bool:
    s = s.strip()
    if re.match(r"^（[一二三四五六七八九十百千]+）", s):
        return True
    if re.match(r"^[（(][一二三四五六七八九十]+[）)]", s):
        return True
    return bool(re.match(r"^([-*•]|\d+[.)]|[a-zA-Z][.)])\s+", s))


def _looks_like_faq_start(s: str) -> bool:
    return bool(re.match(r"^(问|Q|FAQ|问题)[:：]\s*", s, re.I))


def _looks_like_faq_answer_start(s: str) -> bool:
    return bool(re.match(r"^(答|A|回答)[:：]\s*", s, re.I))


def _classify_text_block(body: str) -> str:
    if body.strip().startswith(">"):
        return "quote"
    if _looks_like_text_table(body):
        return "table"
    if any(_is_list_line(ln.strip()) for ln in body.splitlines() if ln.strip()):
        return "list"
    return "paragraph"


def _looks_like_text_table(content: str) -> bool:
    lines = [ln.strip() for ln in content.splitlines() if ln.strip()]
    if len(lines) < 2:
        return False
    pipe_lines = [ln for ln in lines if "|" in ln]
    if len(pipe_lines) >= 2:
        return True
    sep_like = [ln for ln in lines if re.match(r"^[\s\-+:|]{3,}$", ln)]
    return bool(sep_like and pipe_lines)


# --- Plain / PDF page text ---

def normalize_pdf_page_text(raw: str) -> str:
    """PDF 页级清洗：断行拼接、页码/页脚启发式剔除、空白归一。"""
    from app.services.text_sanitize import sanitize_text_for_db

    text = sanitize_text_for_db(raw)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"-\n(?=\w)", "", text)
    text = re.sub(r"(?<=[\u4e00-\u9fff])\n(?=[\u4e00-\u9fff])", "", text)
    lines = text.split("\n")
    cleaned: list[str] = []
    page_num_re = re.compile(r"^\s*(\d{1,3})\s*/\s*\d{1,4}\s*$")
    simple_num_re = re.compile(r"^\s*-?\s*\d{1,3}\s*-\s*$")
    noise_re = re.compile(r"^(版权所有|保密|内部资料|机密|confidential|proprietary)\s*$", re.I)
    for ln in lines:
        s = ln.strip()
        if not s:
            cleaned.append("")
            continue
        if noise_re.match(s):
            continue
        if page_num_re.match(s) or simple_num_re.match(s):
            continue
        if re.match(r"^\s*第\s*\d+\s*页\s*$", s):
            continue
        cleaned.append(ln.rstrip())
    text = "\n".join(cleaned)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return sanitize_text_for_db(text)


def parse_plain_blocks(text: str, *, page_number: int | None, source_type: str) -> list[RawBlock]:
    parts = re.split(r"\n\s*\n", text.strip())
    blocks: list[RawBlock] = []
    for part in parts:
        p = part.strip()
        if not p:
            continue
        first = p.split("\n", 1)[0].strip()
        if _looks_like_faq_start(first) and "\n" in p:
            bt = "faq_pair"
        elif _looks_like_text_table(p):
            bt = "table"
        elif _is_list_block(p) or re.search(r"步骤\s*\d|第\s*[一二三四五六七八九十]\s*步", p):
            bt = "list"
        else:
            bt = "paragraph"
        blocks.append(
            RawBlock(
                text=p,
                block_type=bt,
                heading_path=[],
                section_title=_guess_title_from_text(p),
                page_number=page_number,
                source_type=source_type,
            )
        )
    return blocks


def _is_list_block(p: str) -> bool:
    lines = [ln for ln in p.splitlines() if ln.strip()]
    if len(lines) < 2:
        return _is_list_line(lines[0].strip()) if lines else False
    return sum(1 for ln in lines if _is_list_line(ln.strip())) >= max(2, len(lines) // 2)


def _guess_title_from_text(text: str) -> str | None:
    for line in text.splitlines():
        c = line.strip().strip("#").strip()
        if 4 <= len(c) <= 80:
            return c
    return None


# --- DOCX (paragraphs + tables in document order) ---

def _iter_docx_block_items(document: Any):
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    for child in document.element.body:
        tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
        if tag == "p":
            yield Paragraph(child, document)
        elif tag == "tbl":
            yield Table(child, document)


def _table_to_text(table: Any) -> str:
    rows = []
    for row in table.rows:
        cells = [c.text.strip().replace("\n", " ") for c in row.cells]
        rows.append(" | ".join(cells))
    body = "\n".join(rows)
    return f"[TABLE]\n{body}\n[/TABLE]" if body else ""


def _docx_heading_level(style_name: str) -> int:
    s = (style_name or "").lower()
    m = re.search(r"heading\s*(\d+)", s)
    if m:
        return max(1, min(6, int(m.group(1))))
    if s.startswith("heading"):
        return 1
    return 1


def parse_docx_blocks(file_path: Path) -> list[RawBlock]:
    from docx import Document
    from docx.table import Table as DocxTable
    from docx.text.paragraph import Paragraph as DocxParagraph

    document = Document(str(file_path))
    blocks: list[RawBlock] = []
    heading_stack: list[tuple[int, str]] = []

    def path_titles() -> list[str]:
        return [t for _, t in heading_stack]

    try:
        iterator = _iter_docx_block_items(document)
    except Exception:
        iterator = []

    for item in iterator:
        if isinstance(item, DocxParagraph):
            t = item.text.strip()
            if not t:
                continue
            style = (getattr(item.style, "name", "") or "").lower()
            if style.startswith("heading"):
                level = _docx_heading_level(style)
                while heading_stack and heading_stack[-1][0] >= level:
                    heading_stack.pop()
                heading_stack.append((level, t))
                path = path_titles()
                blocks.append(
                    RawBlock(
                        text=t,
                        block_type="heading",
                        heading_path=list(path),
                        section_title=t,
                        page_number=None,
                        source_type="docx",
                    )
                )
                continue
            path = path_titles()
            st = path[-1] if path else None
            bt = "paragraph"
            if _is_list_line(t.split("\n", 1)[0].strip()):
                bt = "list"
            elif _looks_like_faq_start(t.split("\n", 1)[0].strip()):
                bt = "faq_pair"
            blocks.append(
                RawBlock(
                    text=t,
                    block_type=bt,
                    heading_path=list(path),
                    section_title=st,
                    page_number=None,
                    source_type="docx",
                )
            )
        elif isinstance(item, DocxTable):
            tt = _table_to_text(item).strip()
            if tt:
                path = path_titles()
                st = path[-1] if path else None
                blocks.append(
                    RawBlock(
                        text=tt,
                        block_type="table",
                        heading_path=list(path),
                        section_title=st,
                        page_number=None,
                        source_type="docx",
                    )
                )
    if not blocks:
        current_heading = None
        path_legacy: list[str] = []
        for paragraph in document.paragraphs:
            t = paragraph.text.strip()
            if not t:
                continue
            style_name = (getattr(paragraph.style, "name", "") or "").lower()
            if style_name.startswith("heading"):
                current_heading = t
                path_legacy = [t]
            blocks.append(
                RawBlock(
                    text=t,
                    block_type="paragraph",
                    heading_path=list(path_legacy),
                    section_title=current_heading,
                    page_number=None,
                    source_type="docx",
                )
            )
    return [b for b in blocks if b.text.strip()]


# --- CSV rows ---

def parse_csv_blocks(text: str, source_type: str) -> list[RawBlock]:
    rows = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return [
        RawBlock(
            text=row,
            block_type="table",
            heading_path=["tabular"],
            section_title="tabular_rows",
            page_number=None,
            source_type=source_type,
        )
        for row in rows
    ]


def extract_raw_blocks(file_record: Any, file_path: Path) -> list[RawBlock]:
    from app.services.text_sanitize import sanitize_text_for_db

    ft = (file_record.file_type or "").lower()
    blocks: list[RawBlock]
    if ft == "md":
        blocks = parse_markdown_blocks(sanitize_text_for_db(file_path.read_text(encoding="utf-8")))
    elif ft in {"txt"}:
        blocks = parse_plain_blocks(
            sanitize_text_for_db(file_path.read_text(encoding="utf-8")),
            page_number=None,
            source_type=ft,
        )
    elif ft in {"csv", "tsv"}:
        blocks = parse_csv_blocks(sanitize_text_for_db(file_path.read_text(encoding="utf-8")), ft)
    elif ft == "pdf":
        from PyPDF2 import PdfReader

        reader = PdfReader(str(file_path))
        out: list[RawBlock] = []
        for index, page in enumerate(reader.pages):
            raw = normalize_pdf_page_text(page.extract_text() or "")
            if raw:
                out.extend(
                    parse_plain_blocks(raw, page_number=index + 1, source_type="pdf")
                )
        blocks = out
    elif ft == "docx":
        blocks = parse_docx_blocks(file_path)
    else:
        raise ValueError(f"暂不支持的文件类型: {ft}")
    return [sanitize_raw_block(b) for b in blocks]


def _merge_small_blocks(blocks: list[RawBlock], max_merge_chars: int) -> list[RawBlock]:
    if not blocks:
        return []
    merged: list[RawBlock] = []
    buf: list[RawBlock] = []

    def flush_buf() -> None:
        nonlocal buf
        if not buf:
            return
        if len(buf) == 1:
            merged.append(buf[0])
            buf = []
            return
        texts = "\n\n".join(b.text for b in buf)
        bt = buf[0].block_type
        if any(b.block_type != bt for b in buf):
            bt = "paragraph"
        merged.append(
            RawBlock(
                text=texts,
                block_type=bt,
                heading_path=list(buf[-1].heading_path),
                section_title=buf[-1].section_title,
                page_number=buf[0].page_number,
                source_type=buf[0].source_type,
            )
        )
        buf = []

    for b in blocks:
        if b.block_type in ("table", "code", "faq_pair"):
            flush_buf()
            merged.append(b)
            continue
        if b.block_type == "heading":
            flush_buf()
            merged.append(b)
            continue
        if not buf:
            buf.append(b)
            continue
        cand = "\n\n".join(x.text for x in buf) + "\n\n" + b.text
        same_path = buf[0].heading_path == b.heading_path and buf[0].page_number == b.page_number
        if same_path and len(cand) <= max_merge_chars:
            buf.append(b)
        else:
            flush_buf()
            buf.append(b)
    flush_buf()
    return merged


def group_blocks_into_parents(
    blocks: list[RawBlock],
    *,
    target_chars: int,
    min_chars: int,
    max_chars: int,
) -> list[list[RawBlock]]:
    """在块边界合并为 parent 组，避免跨 table/code 硬切。"""
    groups: list[list[RawBlock]] = []
    cur: list[RawBlock] = []
    cur_len = 0

    def flush() -> None:
        nonlocal cur, cur_len
        if cur:
            groups.append(cur)
        cur = []
        cur_len = 0

    for b in blocks:
        blen = len(b.text)
        if b.block_type in ("table", "code", "faq_pair"):
            if cur:
                flush()
            groups.append([b])
            continue
        if b.block_type == "heading":
            if cur and cur_len >= min_chars:
                flush()
            cur.append(b)
            cur_len += blen + 2
            continue
        if not cur:
            cur.append(b)
            cur_len = blen
            continue
        if cur_len + blen <= max_chars:
            cur.append(b)
            cur_len += blen + 2
            if cur_len >= target_chars:
                flush()
            continue
        if cur_len >= min_chars:
            flush()
        cur = [b]
        cur_len = blen
    flush()
    return [g for g in groups if g]


def split_text_to_children(
    text: str,
    *,
    target_chars: int,
    min_chars: int,
    max_chars: int,
    overlap_chars: int,
    block_type: str,
) -> list[str]:
    """按句界切 child；表格按行组切并重复表头。"""
    t = text.strip()
    if not t:
        return []
    if block_type == "table":
        return _split_table_chunks(t, max_chars, overlap_chars)
    if len(t) <= max_chars:
        return [t] if len(t) >= max(20, app_settings.ingest_min_chunk_chars // 2) else []

    sentences = re.split(r"(?<=[。！？!?])\s*|\n+", t)
    sentences = [s.strip() for s in sentences if s.strip()]
    if len(sentences) <= 1:
        return _split_fixed_window(t, target_chars, max_chars, overlap_chars)

    chunks: list[str] = []
    buf = ""
    for s in sentences:
        cand = f"{buf}{s}" if buf else s
        if len(cand) <= target_chars:
            buf = cand
            continue
        if buf and len(buf) >= min_chars:
            chunks.append(buf)
            tail = buf[-overlap_chars:] if overlap_chars > 0 else ""
            buf = (tail + s).strip() if tail else s
        else:
            buf = cand
        while len(buf) > max_chars:
            chunks.append(buf[:max_chars])
            buf = buf[max_chars - overlap_chars :] if overlap_chars else buf[max_chars:]
    if buf and len(buf) >= min_chars:
        chunks.append(buf)
    elif buf and chunks:
        chunks[-1] = f"{chunks[-1]}\n\n{buf}"
    elif buf:
        chunks.append(buf)
    return [c for c in chunks if len(c.strip()) >= max(20, min_chars // 3)]


def _split_table_chunks(table_text: str, max_chars: int, overlap_chars: int) -> list[str]:
    lines = table_text.splitlines()
    if not lines:
        return []
    header = lines[0]
    rest = lines[1:]
    if len(header) + 4 >= max_chars:
        return _split_fixed_window(table_text, max_chars // 2, max_chars, overlap_chars)
    out: list[str] = []
    buf_lines = [header]
    cur_len = len(header)
    for ln in rest:
        add = len(ln) + 1
        if cur_len + add > max_chars and len(buf_lines) > 1:
            out.append("\n".join(buf_lines))
            buf_lines = [header, ln]
            cur_len = len(header) + add
        else:
            buf_lines.append(ln)
            cur_len += add
    if len(buf_lines) > 1 or (buf_lines and buf_lines[0]):
        out.append("\n".join(buf_lines))
    return out if out else [table_text]


def _split_fixed_window(t: str, target: int, max_c: int, overlap: int) -> list[str]:
    if len(t) <= max_c:
        return [t]
    out: list[str] = []
    i = 0
    while i < len(t):
        piece = t[i : i + max_c]
        if piece.strip():
            out.append(piece.strip())
        i += max(target, 1) - overlap if overlap < target else max_c
    return out if out else [t[:max_c]]


def _truncate_raw_blocks(blocks: list[RawBlock], max_chars: int) -> tuple[list[RawBlock], bool]:
    tot = 0
    out: list[RawBlock] = []
    truncated = False
    for b in blocks:
        if tot >= max_chars:
            truncated = True
            break
        if tot + len(b.text) > max_chars:
            remain = max_chars - tot
            if remain > 80:
                out.append(
                    RawBlock(
                        text=b.text[:remain],
                        block_type=b.block_type,
                        heading_path=list(b.heading_path),
                        section_title=b.section_title,
                        page_number=b.page_number,
                        source_type=b.source_type,
                    )
                )
            truncated = True
            break
        out.append(b)
        tot += len(b.text)
    return out, truncated


def build_rows_spec(
    file_record: Any,
    file_path: Path,
) -> tuple[list[dict], list[str]]:
    """
    返回与 ingest_service 兼容的 rows_spec 列表及 warnings。
    每项: chunk_kind, parent_ref, content, chunk_index(-1), page_number, section_title, metadata_json
    """
    raw = extract_raw_blocks(file_record, file_path)
    raw, trunc = _truncate_raw_blocks(raw, app_settings.ingest_max_index_text_chars)
    warnings: list[str] = []
    if trunc:
        warnings.append(
            f"文件文本较长，结构切块仅保留前 {app_settings.ingest_max_index_text_chars} 个字符"
        )
    merge_cap = approx_chars_for_tokens(app_settings.ingest_parent_target_tokens // 3)
    raw = _merge_small_blocks(raw, max_merge_chars=merge_cap)

    p_tok = app_settings.ingest_parent_target_tokens
    p_min_tok = app_settings.ingest_parent_min_tokens
    p_max_tok = app_settings.ingest_parent_max_tokens
    target_chars = approx_chars_for_tokens(p_tok)
    min_chars = approx_chars_for_tokens(p_min_tok)
    max_chars = approx_chars_for_tokens(p_max_tok)

    parent_groups = group_blocks_into_parents(
        raw, target_chars=target_chars, min_chars=min_chars, max_chars=max_chars
    )

    c_tok = app_settings.ingest_child_target_tokens
    c_min_tok = app_settings.ingest_child_min_tokens
    c_max_tok = app_settings.ingest_child_max_tokens
    ov_tok = app_settings.ingest_child_overlap_tokens
    ct = approx_chars_for_tokens(c_tok)
    cmin = approx_chars_for_tokens(c_min_tok)
    cmax = approx_chars_for_tokens(c_max_tok)
    cov = approx_chars_for_tokens(ov_tok)

    rows_spec: list[dict] = []
    parent_seq = 0

    for group in parent_groups:
        parent_text_parts: list[str] = []
        block_types: list[str] = []
        path: list[str] = []
        sec: str | None = None
        page_no: int | None = None
        src = "text"
        for b in group:
            if b.block_type != "heading":
                parent_text_parts.append(b.text)
            else:
                parent_text_parts.append(b.text)
            block_types.append(b.block_type)
            if b.heading_path:
                path = list(b.heading_path)
            if b.section_title:
                sec = b.section_title
            if b.page_number is not None:
                page_no = b.page_number
            src = b.source_type
        parent_body = "\n\n".join(parent_text_parts).strip()
        if not parent_body:
            continue
        primary_bt = block_types[0] if len(set(block_types)) == 1 else "mixed"
        heading_path_str = _heading_path_str(path)
        seg_hash = hashlib.sha256(parent_body.encode("utf-8")).hexdigest()

        parent_meta: dict[str, Any] = {
            "doc_id": file_record.id,
            "file_id": file_record.id,
            "filename": file_record.file_name,
            "source_file_name": file_record.file_name,
            "page_number": page_no,
            "section_title": sec,
            "heading_path": heading_path_str,
            "section_path": path,
            "parent_section": sec or (path[-1] if path else None),
            "parent_sequence_index": parent_seq,
            "chunk_role": "parent",
            "block_type": primary_bt,
            "block_types": block_types,
            "source_type": src,
            "content_hash": seg_hash,
            "char_count": len(parent_body),
            "approx_tokens": approx_tokens(parent_body),
            "pipeline_version": PIPELINE_VERSION,
        }
        parent_row_index = len(rows_spec)
        rows_spec.append(
            {
                "chunk_kind": "parent",
                "parent_ref": None,
                "content": parent_body,
                "chunk_index": -1,
                "page_number": page_no,
                "section_title": sec,
                "metadata_json": dict(parent_meta),
            }
        )

        children = split_text_to_children(
            parent_body,
            target_chars=ct,
            min_chars=cmin,
            max_chars=cmax,
            overlap_chars=cov,
            block_type=primary_bt if primary_bt != "mixed" else "paragraph",
        )
        if not children:
            children = [parent_body] if len(parent_body.strip()) >= max(20, app_settings.ingest_min_chunk_chars // 2) else []
        if not children:
            warnings.append("某 parent 过短未产生 child，已跳过该段")
            rows_spec.pop()
            continue

        for ci, ch_text in enumerate(children):
            ch = ch_text.strip()
            if not ch:
                continue
            child_meta = {
                **{k: v for k, v in parent_meta.items() if k not in ("chunk_role", "approx_tokens", "char_count")},
                "chunk_role": "child",
                "child_index_in_parent": ci,
                "parent_row_index": parent_row_index,
                "block_type": primary_bt if primary_bt != "mixed" else "paragraph",
                "content_hash": hashlib.sha256(ch.encode("utf-8")).hexdigest(),
                "char_count": len(ch),
                "approx_tokens": approx_tokens(ch),
                "pipeline_version": PIPELINE_VERSION,
            }
            rows_spec.append(
                {
                    "chunk_kind": "child",
                    "parent_ref": parent_row_index,
                    "content": ch,
                    "chunk_index": -1,
                    "page_number": page_no,
                    "section_title": sec,
                    "metadata_json": child_meta,
                }
            )
        parent_seq += 1

    # 邻接 child 逻辑序号（同文件内按 rows_spec 顺序）
    child_entries = [(i, r) for i, r in enumerate(rows_spec) if r["chunk_kind"] == "child"]
    for j, (idx, _) in enumerate(child_entries):
        meta = rows_spec[idx]["metadata_json"]
        meta["child_sequence_in_file"] = j
        if j > 0:
            meta["prev_sibling_row_offset"] = idx - child_entries[j - 1][0]
        if j + 1 < len(child_entries):
            meta["next_sibling_row_offset"] = child_entries[j + 1][0] - idx

    return rows_spec, warnings
