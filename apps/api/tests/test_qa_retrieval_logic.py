import unittest

from app.services.qa_service import (
    _dominance_guardrail,
    _diversity_rerank_matches,
    _pack_context_and_references,
    _select_doc_aware_matches,
    _build_retrieval_meta,
    _build_query_variants,
    _assemble_evidence_bundles,
    _is_grounded_answer,
    _normalize_retrieval_mode,
    _score_threshold_for_mode,
)
from app.services.qa_agent_workflow import classify_task_type, plan_retrieval


class TestQARetrievalLogic(unittest.TestCase):
    def test_normalize_retrieval_mode(self):
        self.assertEqual(_normalize_retrieval_mode("semantic"), "semantic")
        self.assertEqual(_normalize_retrieval_mode("lexical"), "lexical")
        self.assertEqual(_normalize_retrieval_mode("hybrid"), "hybrid")
        self.assertEqual(_normalize_retrieval_mode("invalid"), "hybrid")
        self.assertEqual(_normalize_retrieval_mode(None), "hybrid")

    def test_thresholds_by_mode(self):
        sem = _score_threshold_for_mode("semantic")
        lex = _score_threshold_for_mode("lexical")
        hyb = _score_threshold_for_mode("hybrid")
        self.assertTrue(sem >= 0.0)
        self.assertTrue(lex >= 0.0)
        self.assertTrue(hyb >= 0.0)

    def test_query_variants_non_empty(self):
        out = _build_query_variants("  什么是RAG系统的召回率优化？ ")
        self.assertTrue(out)
        self.assertTrue(all(isinstance(x, str) and x.strip() for x in out))

    def test_retrieval_meta_uses_mode_threshold(self):
        meta = _build_retrieval_meta(
            retrieval_strategy="pgvector_ann_hnsw",
            answer_source="knowledge_base",
            scope_type="all",
            strict_mode=False,
            top_k=6,
            compatible_file_count=1,
            candidate_chunks=5,
            matched_chunks=3,
            selected_chunks=3,
            used_file_ids=[1],
            candidate_k=8,
            expanded_chunks=3,
            packed_chunks=3,
            context_chars=500,
            neighbor_window=1,
            dedupe_adjacent_chunks=True,
            retrieval_mode="hybrid",
            semantic_candidate_count=4,
            lexical_candidate_count=4,
            fusion_method="rrf",
            score_threshold_applied=0.012,
            rerank_enabled=True,
            rerank_input_count=5,
            rerank_output_count=5,
            rerank_model_name="mock",
            rerank_applied=True,
            task_type="simple_qa",
            planner_output={"selected_strategy": "light_qa"},
            selected_strategy="light_qa",
            workflow_steps_json=[{"step": "plan_retrieval", "status": "completed"}],
            tool_traces_json=[{"tool": "classify_task_type"}],
            session_context_json={"scope_type": "all"},
            final_answer_type="knowledge_base",
        )
        self.assertEqual(meta["min_similarity_score"], 0.012)
        self.assertEqual(meta["min_score"], 0.012)
        self.assertEqual(meta["rewritten_queries"], [])
        self.assertEqual(meta["task_type"], "simple_qa")
        self.assertEqual(meta["selected_strategy"], "light_qa")

    def test_task_router_and_planner(self):
        routing = classify_task_type(
            question="请比较方案A和方案B的优缺点",
            scope_type="files",
            file_ids=[1, 2],
        )
        self.assertEqual(routing["task_type"], "compare")
        plan = plan_retrieval(
            task_type=routing["task_type"],
            normalized_query="请比较方案A和方案B的优缺点",
            rewritten_queries=["请比较方案A和方案B的优缺点"],
            scope_type="files",
            strict_mode=True,
            top_k=4,
            candidate_k=4,
            file_ids=[1, 2],
        )
        self.assertEqual(plan["selected_strategy"], "compare_dual_focus")
        self.assertGreaterEqual(plan["top_k"], 6)

    def test_grounded_answer_guard(self):
        self.assertFalse(_is_grounded_answer("", [{"chunk_id": 1}]))
        self.assertFalse(_is_grounded_answer("ok", []))
        self.assertTrue(_is_grounded_answer("ok", [{"chunk_id": 1}]))

    def test_doc_cap_selection(self):
        items = [
            {"chunk": type("C", (), {"id": 1, "file_id": 10, "chunk_index": 0}), "score": 0.9},
            {"chunk": type("C", (), {"id": 2, "file_id": 10, "chunk_index": 1}), "score": 0.8},
            {"chunk": type("C", (), {"id": 3, "file_id": 10, "chunk_index": 2}), "score": 0.7},
            {"chunk": type("C", (), {"id": 4, "file_id": 11, "chunk_index": 0}), "score": 0.69},
        ]
        out = _select_doc_aware_matches(
            items,
            max_chunks_per_doc=2,
            target_distinct_docs=2,
            top_k=4,
            allow_single_doc_dominance=False,
        )
        per_doc = {}
        for it in out:
            per_doc[it["chunk"].file_id] = per_doc.get(it["chunk"].file_id, 0) + 1
        self.assertLessEqual(per_doc[10], 2)
        self.assertIn(11, per_doc)

    def test_dominance_guardrail(self):
        strong = [
            {"chunk": type("C", (), {"id": 1, "file_id": 1, "chunk_index": 0}), "score": 0.95},
            {"chunk": type("C", (), {"id": 2, "file_id": 2, "chunk_index": 0}), "score": 0.4},
        ]
        balanced = [
            {"chunk": type("C", (), {"id": 1, "file_id": 1, "chunk_index": 0}), "score": 0.75},
            {"chunk": type("C", (), {"id": 2, "file_id": 2, "chunk_index": 0}), "score": 0.7},
        ]
        self.assertTrue(_dominance_guardrail(strong, dominance_ratio=1.6))
        self.assertFalse(_dominance_guardrail(balanced, dominance_ratio=1.6))

    def test_diversity_rerank_toggle(self):
        items = [
            {"chunk": type("C", (), {"id": 1, "file_id": 1, "chunk_index": 0, "content": "alpha beta"}), "score": 0.9},
            {"chunk": type("C", (), {"id": 2, "file_id": 1, "chunk_index": 1, "content": "alpha beta"}), "score": 0.88},
            {"chunk": type("C", (), {"id": 3, "file_id": 2, "chunk_index": 0, "content": "gamma delta"}), "score": 0.7},
        ]
        off, off_applied = _diversity_rerank_matches(
            items, enabled=False, diversity_lambda=0.7, fetch_k=3, redundancy_sim_threshold=0.9
        )
        on, on_applied = _diversity_rerank_matches(
            items, enabled=True, diversity_lambda=0.7, fetch_k=3, redundancy_sim_threshold=0.9
        )
        self.assertFalse(off_applied)
        self.assertTrue(on_applied)
        self.assertEqual(off[0]["chunk"].id, 1)
        self.assertEqual(on[1]["chunk"].file_id, 2)

    def test_adjacent_redundancy_suppression(self):
        c1 = type("C", (), {"id": 1, "file_id": 1, "chunk_index": 1, "content": "a b c d", "section_title": None, "page_number": None})
        c2 = type("C", (), {"id": 2, "file_id": 1, "chunk_index": 2, "content": "a b c d", "section_title": None, "page_number": None})
        c3 = type("C", (), {"id": 3, "file_id": 2, "chunk_index": 1, "content": "x y z", "section_title": None, "page_number": None})
        blocks, refs, _, _, packed, _, rate = _pack_context_and_references(
            [{"chunk": c1, "file_name": "f1", "score": 0.9}, {"chunk": c2, "file_name": "f1", "score": 0.8}, {"chunk": c3, "file_name": "f2", "score": 0.7}],
            seed_chunk_ids={1, 2, 3},
            max_context_chars=2000,
            dedupe_adjacent_chunks=True,
            redundancy_sim_threshold=0.8,
            redundancy_adjacent_window=1,
        )
        self.assertEqual(len(blocks), 2)
        self.assertEqual(len(refs), 2)
        self.assertEqual(packed, 2)
        self.assertGreater(rate, 0.0)

    def test_evidence_bundle_grouping(self):
        refs = [
            {"file_id": 1, "file_name": "a.md", "chunk_id": 10, "chunk_index": 1, "score": 0.9},
            {"file_id": 1, "file_name": "a.md", "chunk_id": 11, "chunk_index": 2, "score": 0.7},
            {"file_id": 2, "file_name": "b.md", "chunk_id": 20, "chunk_index": 5, "score": 0.8},
        ]
        out = _assemble_evidence_bundles(refs)
        self.assertEqual(out["source_count"], 2)
        self.assertEqual(out["primary_sources"][0]["file_id"], 1)


if __name__ == "__main__":
    unittest.main()
