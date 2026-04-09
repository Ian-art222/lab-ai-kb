"""Coverage sufficiency for answer layer (no DB)."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from app.services.qa_guardrails import assess_coverage_sufficiency_for_answer
from app.services.qa_synthesis import build_answer_synthesis_addon
from app.services.query_understanding import QUERY_TYPE_COMPARE, QUERY_TYPE_MULTI_HOP, QUERY_TYPE_SUMMARY


class TestCoverageGuardrails(unittest.TestCase):
    def test_compare_single_file_is_poor_or_limited(self):
        r = assess_coverage_sufficiency_for_answer(
            query_type=QUERY_TYPE_COMPARE,
            distinct_files_post_pack=1,
            dominant_file_ratio_post_pack=0.95,
            conflict_hint={"likely_conflict": False},
            coverage_diagnostics=None,
        )
        self.assertIn(r["coverage_assessment"], ("coverage_poor", "coverage_limited"))
        self.assertTrue(r.get("requires_multi_source_but_missing"))

    def test_summary_two_files_ok(self):
        r = assess_coverage_sufficiency_for_answer(
            query_type=QUERY_TYPE_SUMMARY,
            distinct_files_post_pack=2,
            dominant_file_ratio_post_pack=0.5,
            conflict_hint={"likely_conflict": False},
            coverage_diagnostics={"weak_query_indices": []},
        )
        self.assertEqual(r["coverage_assessment"], "coverage_good")

    def test_dominant_ratio_triggers_warning_flag(self):
        r = assess_coverage_sufficiency_for_answer(
            query_type=QUERY_TYPE_MULTI_HOP,
            distinct_files_post_pack=2,
            dominant_file_ratio_post_pack=0.9,
            conflict_hint={"likely_conflict": False},
            coverage_diagnostics=None,
        )
        self.assertTrue(r.get("dominant_source_warning") or r["coverage_assessment"] != "coverage_good")

    @patch("app.services.qa_synthesis.app_settings")
    def test_strict_mode_prompt_injection(self, m):
        m.qa_enable_answer_style_by_query_type = False
        m.qa_enable_evidence_sufficiency_guard = False
        m.qa_enable_conflict_notice = False
        m.qa_enable_coverage_shortfall_guard = True
        cov = assess_coverage_sufficiency_for_answer(
            query_type=QUERY_TYPE_COMPARE,
            distinct_files_post_pack=1,
            dominant_file_ratio_post_pack=0.9,
            conflict_hint={"likely_conflict": False},
            coverage_diagnostics=None,
        )
        text, trace = build_answer_synthesis_addon(
            query_type=QUERY_TYPE_COMPARE,
            task_type="compare",
            sufficiency={"level": "strong"},
            conflict_hint={"likely_conflict": False},
            reference_count=2,
            distinct_files=1,
            coverage_assessment=cov,
            strict_mode=True,
        )
        self.assertTrue(trace.get("coverage_shortfall_prompt_applied"))
        self.assertIn("严格模式", text)


if __name__ == "__main__":
    unittest.main()
