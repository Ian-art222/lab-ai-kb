import unittest
from types import SimpleNamespace

from app.core.config import settings as app_settings
from app.services import qa_service


def _mk_item(file_id: int, chunk_index: int, score: float, text: str, cid: int):
    return {
        "chunk": SimpleNamespace(
            id=cid,
            file_id=file_id,
            chunk_index=chunk_index,
            content=text,
            section_title=None,
            page_number=None,
        ),
        "file_name": f"f{file_id}.md",
        "folder_id": 1,
        "score": score,
    }


class TestQARetrievalLogic(unittest.TestCase):
    def setUp(self):
        self._bak = {
            "qa_diversity_rerank_enabled": app_settings.qa_diversity_rerank_enabled,
            "qa_diversity_lambda": app_settings.qa_diversity_lambda,
            "qa_max_chunks_per_doc": app_settings.qa_max_chunks_per_doc,
            "qa_target_distinct_docs": app_settings.qa_target_distinct_docs,
            "qa_min_distinct_docs_for_multi_source": app_settings.qa_min_distinct_docs_for_multi_source,
            "qa_single_doc_dominance_ratio": app_settings.qa_single_doc_dominance_ratio,
            "qa_merge_adjacent_gap": app_settings.qa_merge_adjacent_gap,
            "qa_redundancy_sim_threshold": app_settings.qa_redundancy_sim_threshold,
        }

    def tearDown(self):
        for k, v in self._bak.items():
            setattr(app_settings, k, v)

    def test_per_doc_cap_enforced(self):
        app_settings.qa_max_chunks_per_doc = 2
        app_settings.qa_target_distinct_docs = 2
        app_settings.qa_min_distinct_docs_for_multi_source = 2
        app_settings.qa_single_doc_dominance_ratio = 10.0
        items = [
            _mk_item(1, 0, 0.9, "alpha", 1),
            _mk_item(1, 1, 0.85, "alpha next", 2),
            _mk_item(1, 2, 0.83, "alpha next 2", 3),
            _mk_item(2, 0, 0.82, "beta", 4),
        ]
        out = qa_service._enforce_doc_diversity(items)
        doc1 = [x for x in out if x["chunk"].file_id == 1]
        self.assertLessEqual(len(doc1), 2)

    def test_dominance_guardrail_allows_single_doc_focus(self):
        app_settings.qa_max_chunks_per_doc = 3
        app_settings.qa_target_distinct_docs = 2
        app_settings.qa_min_distinct_docs_for_multi_source = 2
        app_settings.qa_single_doc_dominance_ratio = 1.2
        items = [
            _mk_item(1, 0, 0.96, "dominant", 1),
            _mk_item(1, 1, 0.95, "dominant2", 2),
            _mk_item(2, 0, 0.70, "weak", 3),
        ]
        out = qa_service._enforce_doc_diversity(items)
        self.assertGreaterEqual(len([x for x in out if x["chunk"].file_id == 1]), 2)

    def test_diversity_rerank_penalizes_adjacent_redundancy(self):
        app_settings.qa_diversity_rerank_enabled = True
        app_settings.qa_diversity_lambda = 0.9
        app_settings.qa_merge_adjacent_gap = 1
        app_settings.qa_redundancy_sim_threshold = 0.5
        items = [
            _mk_item(1, 0, 0.95, "A B C D", 1),
            _mk_item(1, 1, 0.94, "A B C D", 2),
            _mk_item(2, 0, 0.90, "X Y Z", 3),
        ]
        out = qa_service._apply_diversity_rerank(items)
        self.assertEqual(out[0]["chunk"].file_id, 1)
        self.assertEqual(out[1]["chunk"].file_id, 2)


if __name__ == "__main__":
    unittest.main()
