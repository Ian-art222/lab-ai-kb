#!/usr/bin/env python3
"""Smoke: coverage-aware packing + diagnostics (no DB). Run: python scripts/smoke_context_packing.py from apps/api."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from types import SimpleNamespace

from app.services.context_packing import (
    build_coverage_diagnostics_payload,
    select_pack_items_coverage_two_phase,
)
from app.services.query_understanding import QUERY_TYPE_COMPARE


def _chunk(cid: int, fid: int):
    return SimpleNamespace(
        id=cid,
        file_id=fid,
        chunk_index=cid,
        content=f"c{cid}",
        metadata_json={},
        parent_chunk_id=None,
        section_title=None,
        page_number=None,
    )


def main() -> None:
    items = [
        {"chunk": _chunk(1, 10), "score": 0.99, "rerank_score": 0.99, "matched_query_index": 0, "file_name": "a.pdf"},
        {"chunk": _chunk(2, 10), "score": 0.98, "rerank_score": 0.98, "matched_query_index": 0, "file_name": "a.pdf"},
        {"chunk": _chunk(3, 20), "score": 0.45, "rerank_score": 0.45, "matched_query_index": 1, "file_name": "b.pdf"},
    ]
    qt = QUERY_TYPE_COMPARE
    selected, trace = select_pack_items_coverage_two_phase(
        items,
        query_type=qt,
        seed_chunk_ids={1},
        max_total=4,
    )
    pre_files = len({int(x["chunk"].file_id) for x in items})
    post_files = len({int(x["chunk"].file_id) for x in selected})
    print("query_type:", qt)
    print("pre-pack distinct files (candidates):", pre_files)
    print("post-select distinct files:", post_files)
    print("coverage select trace:", {k: trace[k] for k in trace if k != "coverage_constraints_applied"})

    refs = []
    for it in selected:
        ch = it["chunk"]
        refs.append(
            {
                "file_id": int(ch.file_id),
                "parent_chunk_id": None,
                "matched_query_index": int(it.get("matched_query_index", -1)),
            }
        )
    packing_trace = {"per_file_context_chars": {"10": 800, "20": 200}}
    diag = build_coverage_diagnostics_payload(
        pre_pack_items=list(selected),
        references=refs,
        retrieval_queries=["qA", "qB"],
        reliable_matches=items,
        query_type=qt,
        coverage_select_trace=trace,
        packing_trace=packing_trace,
    )
    print("dominant_file_ratio_post_pack (chars):", diag.get("dominant_file_ratio_post_pack"))
    print("dominant_file_ratio_chunks:", diag.get("dominant_file_ratio_chunks"))
    for it in selected:
        ch = it["chunk"]
        print(
            "  chunk",
            ch.id,
            "file",
            ch.file_id,
            "matched_query_index",
            it.get("matched_query_index"),
            "(provenance tagging happens in qa_service._pack_context_and_references)",
        )


if __name__ == "__main__":
    main()
