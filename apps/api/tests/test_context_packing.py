"""Coverage-aware packing selection (mock chunks, no DB)."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.services.context_packing import select_pack_items_coverage_two_phase
from app.services.query_understanding import QUERY_TYPE_COMPARE, QUERY_TYPE_PROCEDURE


def _chunk(cid: int, fid: int, idx: int = 0, pid: int | None = None):
    return SimpleNamespace(
        id=cid,
        file_id=fid,
        chunk_index=idx,
        content=f"body-{cid}",
        metadata_json={},
        parent_chunk_id=pid,
        section_title=None,
        page_number=None,
    )


def _item(cid: int, fid: int, score: float, *, text: str | None = None, pid: int | None = None, qi: int = 0):
    ch = _chunk(cid, fid, idx=cid, pid=pid)
    it = {
        "chunk": ch,
        "score": score,
        "rerank_score": score,
        "matched_query_index": qi,
        "file_name": f"f{fid}.pdf",
    }
    if text is not None:
        it["_pack_text_primary"] = text
        it["_pack_text"] = text
    return it


class TestCoverageTwoPhase(unittest.TestCase):
    @patch("app.services.context_packing.app_settings")
    def test_compare_keeps_multiple_files(self, m):
        m.qa_coverage_max_parents_per_file = 4
        m.qa_max_dominant_file_ratio = 0.65
        m.qa_redundancy_jaccard_threshold_coverage = 0.72
        m.qa_enable_redundancy_penalty_coverage = True
        m.qa_enable_heading_diversity_bonus = True
        m.qa_enable_dominant_source_penalty = True
        items = [
            _item(1, 10, 0.99),
            _item(2, 10, 0.98),
            _item(3, 10, 0.97),
            _item(4, 11, 0.50),
            _item(5, 12, 0.49),
        ]
        selected, trace = select_pack_items_coverage_two_phase(
            items,
            query_type=QUERY_TYPE_COMPARE,
            seed_chunk_ids={1},
            max_total=4,
        )
        files = {int(x["chunk"].file_id) for x in selected}
        self.assertGreaterEqual(len(files), 2, msg=f"expected >=2 files, got {files} trace={trace}")

    @patch("app.services.context_packing.app_settings")
    def test_monopoly_file_still_yields_second_file_seed(self, m):
        m.qa_coverage_max_parents_per_file = 4
        m.qa_max_dominant_file_ratio = 0.65
        m.qa_redundancy_jaccard_threshold_coverage = 0.72
        m.qa_enable_redundancy_penalty_coverage = False
        m.qa_enable_heading_diversity_bonus = False
        m.qa_enable_dominant_source_penalty = False
        items = [
            _item(1, 10, 1.0),
            _item(2, 10, 0.99),
            _item(3, 10, 0.98),
            _item(4, 20, 0.40),
        ]
        selected, _trace = select_pack_items_coverage_two_phase(
            items,
            query_type=QUERY_TYPE_COMPARE,
            seed_chunk_ids={1, 2, 3},
            max_total=3,
        )
        files = {int(x["chunk"].file_id) for x in selected}
        self.assertIn(20, files)

    @patch("app.services.context_packing.app_settings")
    def test_procedure_allows_single_file_focus(self, m):
        m.qa_coverage_max_parents_per_file = 2
        m.qa_max_dominant_file_ratio = 0.65
        m.qa_redundancy_jaccard_threshold_coverage = 0.72
        m.qa_enable_redundancy_penalty_coverage = True
        m.qa_enable_heading_diversity_bonus = True
        m.qa_enable_dominant_source_penalty = True
        # 仅单文件候选：procedure 的 target_distinct_files=1，不应为扩覆盖引入其他文件
        items = [_item(1, 10, 0.9), _item(2, 10, 0.8)]
        selected, _ = select_pack_items_coverage_two_phase(
            items,
            query_type=QUERY_TYPE_PROCEDURE,
            seed_chunk_ids={1},
            max_total=2,
        )
        self.assertTrue(all(int(x["chunk"].file_id) == 10 for x in selected))

    @patch("app.services.context_packing.app_settings")
    def test_redundancy_penalty_reduces_duplicate_text_preference(self, m):
        m.qa_coverage_max_parents_per_file = 4
        m.qa_max_dominant_file_ratio = 0.95
        m.qa_redundancy_jaccard_threshold_coverage = 0.3
        m.qa_enable_redundancy_penalty_coverage = True
        m.qa_enable_heading_diversity_bonus = False
        m.qa_enable_dominant_source_penalty = False
        dup = "alpha beta gamma delta epsilon zeta eta theta"
        items = [
            _item(1, 10, 1.0, text=dup),
            _item(2, 10, 0.95, text=dup + " tweak"),
            _item(3, 11, 0.50, text="completely different content about other topics"),
        ]
        selected, _ = select_pack_items_coverage_two_phase(
            items,
            query_type=QUERY_TYPE_COMPARE,
            seed_chunk_ids={1},
            max_total=3,
        )
        ids = [int(x["chunk"].id) for x in selected]
        self.assertIn(3, ids, msg="diverse-file chunk should survive redundancy pressure")


if __name__ == "__main__":
    unittest.main()
