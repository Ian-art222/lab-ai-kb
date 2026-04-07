import unittest

from app.services.qa_service import (
    _build_retrieval_meta,
    _build_query_variants,
    _is_grounded_answer,
    _normalize_retrieval_mode,
    _score_threshold_for_mode,
)


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
        )
        self.assertEqual(meta["min_similarity_score"], 0.012)
        self.assertEqual(meta["min_score"], 0.012)

    def test_grounded_answer_guard(self):
        self.assertFalse(_is_grounded_answer("", [{"chunk_id": 1}]))
        self.assertFalse(_is_grounded_answer("ok", []))
        self.assertTrue(_is_grounded_answer("ok", [{"chunk_id": 1}]))


if __name__ == "__main__":
    unittest.main()
