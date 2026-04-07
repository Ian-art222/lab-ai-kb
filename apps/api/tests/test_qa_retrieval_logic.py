import unittest

from app.services.qa_service import (
    _build_query_variants,
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


if __name__ == "__main__":
    unittest.main()
