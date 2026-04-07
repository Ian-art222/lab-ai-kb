import json
import tempfile
import unittest
from pathlib import Path

from evals.runners.run_phase2_eval import run_eval


class TestPhase2EvalRunner(unittest.TestCase):
    def test_run_eval_outputs_reports(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            dataset = root / "dataset.jsonl"
            preds = root / "preds.jsonl"
            out_json = root / "report.json"
            out_md = root / "report.md"
            out_failure = root / "failure.jsonl"
            dataset.write_text(
                json.dumps({"id": "q1", "query": "a", "expected_behavior": "abstain", "category": "no_answer"}) + "\n",
                encoding="utf-8",
            )
            preds.write_text(
                json.dumps(
                    {
                        "id": "q1",
                        "query": "a",
                        "predicted_answer": "无法回答",
                        "abstained": True,
                        "abstain_reason": "no_retrieval_hit",
                        "retrieved_sources": [],
                        "citation_count": 0,
                        "latency_ms": 100,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            report = run_eval(dataset, preds, out_json, out_md, out_failure)
            self.assertEqual(report["summary"]["total"], 1)
            self.assertTrue(out_json.exists())
            self.assertTrue(out_md.exists())
            self.assertTrue(out_failure.exists())


if __name__ == "__main__":
    unittest.main()

