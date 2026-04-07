import unittest

from app.services.qa_service import (
    _apply_diversity_rerank,
    _build_query_variants,
    _enforce_doc_diversity,
    _normalize_retrieval_mode,
    _score_threshold_for_mode,
)


class TestQARetrievalLogic(unittest.TestCase):
    class _Chunk:
        def __init__(self, cid: int, file_id: int, chunk_index: int, content: str):
            self.id = cid
            self.file_id = file_id
            self.chunk_index = chunk_index
            self.content = content

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

    def test_per_doc_cap_effective(self):
        items = [
            {"chunk": self._Chunk(1, 1, 1, "a"), "score": 0.9, "file_name": "f1", "folder_id": None},
            {"chunk": self._Chunk(2, 1, 2, "b"), "score": 0.89, "file_name": "f1", "folder_id": None},
            {"chunk": self._Chunk(3, 1, 3, "c"), "score": 0.88, "file_name": "f1", "folder_id": None},
            {"chunk": self._Chunk(4, 2, 1, "d"), "score": 0.86, "file_name": "f2", "folder_id": None},
        ]
        out = _enforce_doc_diversity(items)
        per_doc = {}
        for it in out:
            did = it["chunk"].file_id
            per_doc[did] = per_doc.get(did, 0) + 1
        self.assertTrue(all(v <= 3 for v in per_doc.values()))

    def test_diversity_rerank_runs(self):
        items = [
            {"chunk": self._Chunk(1, 1, 1, "alpha beta"), "score": 0.9, "file_name": "f1", "folder_id": None},
            {"chunk": self._Chunk(2, 1, 2, "alpha beta gamma"), "score": 0.89, "file_name": "f1", "folder_id": None},
            {"chunk": self._Chunk(3, 2, 1, "delta epsilon"), "score": 0.85, "file_name": "f2", "folder_id": None},
        ]
        out = _apply_diversity_rerank(items)
        self.assertEqual(len(out), len(items))


if __name__ == "__main__":
    unittest.main()
