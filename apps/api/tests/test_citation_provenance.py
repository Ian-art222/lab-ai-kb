"""Provenance resolution + diagnostics payload shape (no DB)."""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from app.schemas.qa import QACitationReferencePayload, RetrievalMetaPayload
from app.services.context_packing import (
    PROVENANCE_ADJACENT_PARENT,
    PROVENANCE_NEIGHBOR_EXPANSION,
    PROVENANCE_PARENT_RECOVERY,
    PROVENANCE_RETRIEVED_HIT,
    build_coverage_diagnostics_payload,
    resolve_pack_provenance,
)


def _ch(cid: int, fid: int = 1):
    return SimpleNamespace(
        id=cid,
        file_id=fid,
        chunk_index=cid,
        content="x",
        metadata_json={},
        parent_chunk_id=None,
        section_title=None,
        page_number=None,
    )


class TestProvenance(unittest.TestCase):
    def test_retrieved_hit(self):
        it = {"chunk": _ch(1), "source_reason": "retrieval_hit"}
        p, tags, role = resolve_pack_provenance(it, {1})
        self.assertEqual(p, PROVENANCE_RETRIEVED_HIT)
        self.assertEqual(role, "retrieval_hit_child")
        self.assertIn(PROVENANCE_RETRIEVED_HIT, tags)

    def test_neighbor_expansion(self):
        it = {"chunk": _ch(2), "source_reason": "neighbor_expansion"}
        p, _tags, _role = resolve_pack_provenance(it, {1})
        self.assertEqual(p, PROVENANCE_NEIGHBOR_EXPANSION)

    def test_parent_recovery(self):
        it = {"chunk": _ch(1), "source_reason": "retrieval_hit", "_used_parent_for_pack": True}
        p, tags, _role = resolve_pack_provenance(it, {1})
        self.assertEqual(p, PROVENANCE_PARENT_RECOVERY)
        self.assertIn(PROVENANCE_PARENT_RECOVERY, tags)

    def test_adjacent_parent(self):
        it = {
            "chunk": _ch(1),
            "source_reason": "retrieval_hit",
            "_used_parent_for_pack": True,
            "_context_adjacent_expanded": True,
        }
        p, tags, _role = resolve_pack_provenance(it, {1})
        self.assertEqual(p, PROVENANCE_ADJACENT_PARENT)
        self.assertIn(PROVENANCE_ADJACENT_PARENT, tags)
        self.assertIn(PROVENANCE_PARENT_RECOVERY, tags)

    def test_schema_roundtrip(self):
        ref = {
            "file_id": 1,
            "chunk_id": 2,
            "provenance_type": PROVENANCE_NEIGHBOR_EXPANSION,
            "context_chunk_role": "neighbor_chunk_context",
            "matched_query_index": 1,
            "rerank_score": 0.5,
        }
        QACitationReferencePayload.model_validate(ref)
        meta = RetrievalMetaPayload.model_validate(
            {
                "retrieval_strategy": "x",
                "answer_source": "knowledge_base",
                "scope_type": "all",
                "strict_mode": True,
                "top_k": 3,
                "min_similarity_score": 0.1,
                "candidate_chunks": 1,
                "matched_chunks": 1,
                "selected_chunks": 1,
                "compatible_file_count": 1,
                "used_file_ids": [1],
                "coverage_diagnostics": {"distinct_files_post_pack": 1},
            }
        )
        self.assertIsNotNone(meta.coverage_diagnostics)

    def test_build_coverage_diagnostics_payload(self):
        pre = [
            {
                "chunk": _ch(1, 10),
                "score": 1.0,
                "matched_query_index": 0,
                "file_name": "a.pdf",
            },
            {
                "chunk": _ch(2, 20),
                "score": 0.5,
                "matched_query_index": 1,
                "file_name": "b.pdf",
            },
        ]
        refs = [
            {
                "file_id": 10,
                "parent_chunk_id": None,
                "matched_query_index": 0,
            }
        ]
        payload = build_coverage_diagnostics_payload(
            pre_pack_items=pre,
            references=refs,
            retrieval_queries=["q0", "q1"],
            reliable_matches=pre,
            query_type="compare",
            coverage_select_trace={"packing_strategy_version": "t"},
            packing_trace={"per_file_context_chars": {"10": 100}},
        )
        self.assertIn("unmatched_queries", payload)
        self.assertIn("weak_query_indices", payload)
        by_q = payload.get("coverage_by_query", {})
        inner = by_q.get("by_index", {})
        self.assertIn("0", inner)
        self.assertIn("final_kept", inner["0"])


if __name__ == "__main__":
    unittest.main()
