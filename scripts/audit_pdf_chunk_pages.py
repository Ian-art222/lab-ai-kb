#!/usr/bin/env python3
"""
Offline audit: for real PDFs, detect parent groups that merge blocks from multiple
page_numbers (=> child text may span pages but carries a single page_number label).
Run from repo root: python scripts/audit_pdf_chunk_pages.py
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
API = ROOT / "apps" / "api"
sys.path.insert(0, str(API))

from app.core.config import settings as app_settings  # noqa: E402
from app.services.chunk_pipeline import (  # noqa: E402
    RawBlock,
    approx_chars_for_tokens,
    extract_raw_blocks,
    group_blocks_into_parents,
    _merge_small_blocks,
    _truncate_raw_blocks,
)


def analyze_pdf(path: Path, label: str) -> None:
    fr = SimpleNamespace(id=999, file_name=path.name, file_type="pdf", folder_id=1)
    raw = extract_raw_blocks(fr, path)
    raw, _trunc = _truncate_raw_blocks(raw, app_settings.ingest_max_index_text_chars)
    merge_cap = approx_chars_for_tokens(app_settings.ingest_parent_target_tokens // 3)
    raw = _merge_small_blocks(raw, max_merge_chars=merge_cap)

    p_tok = app_settings.ingest_parent_target_tokens
    p_min_tok = app_settings.ingest_parent_min_tokens
    p_max_tok = app_settings.ingest_parent_max_tokens
    target_chars = approx_chars_for_tokens(p_tok)
    min_chars = approx_chars_for_tokens(p_min_tok)
    max_chars = approx_chars_for_tokens(p_max_tok)

    groups = group_blocks_into_parents(
        raw, target_chars=target_chars, min_chars=min_chars, max_chars=max_chars
    )

    lens = sorted((len(b.text) for b in raw), reverse=True)
    print(
        f"  [{label}] raw_block_count={len(raw)} "
        f"max_block_chars={lens[0] if lens else 0} "
        f"p50_block_chars={lens[len(lens) // 2] if lens else 0}"
    )

    multi_page_parents = 0
    for gi, group in enumerate(groups):
        pages = {b.page_number for b in group if b.page_number is not None}
        if len(pages) > 1:
            multi_page_parents += 1
            preview = (group[0].text or "")[:80].replace("\n", " ")
            print(
                f"  [{label}] parent_group#{gi}: pages={sorted(pages)} "
                f"blocks={len(group)} first_block_preview={preview!r}"
            )
    # Count approximate children via split logic is heavy; report parent stats only.
    print(
        f"  [{label}] total_blocks={len(raw)} parent_groups={len(groups)} "
        f"multi_page_parent_groups={multi_page_parents}"
    )


def main() -> None:
    pdfs = list((ROOT / ".audit-pdfs").glob("*.pdf"))
    if not pdfs:
        print("No PDFs in .audit-pdfs/ — add samples first.")
        return
    print(
        f"ingest_parent_target_tokens={app_settings.ingest_parent_target_tokens} "
        f"-> target_chars~{approx_chars_for_tokens(app_settings.ingest_parent_target_tokens)}"
    )
    for p in sorted(pdfs):
        print(f"\n=== {p.name} ===")
        analyze_pdf(p, p.name)


if __name__ == "__main__":
    main()
