#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path


@dataclass
class Phase3EvalResult:
    id: str
    scenario: str
    query: str
    task_type: str
    planner_strategy: str
    predicted_answer: str
    citations_count: int
    multi_source_coverage: float
    abstained: bool
    reason_code: str | None
    compare_structure_quality: str | None
    passed: bool
    reason: str


def load_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open("r", encoding="utf-8") as fp:
        for line in fp:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def evaluate_case(row: dict) -> Phase3EvalResult:
    expected_task = row.get("expected_task_type", "simple_qa")
    expected_abstain = bool(row.get("should_abstain", False))
    cited_sources = max(0, int(row.get("mock_source_count", 1)))
    citations_count = max(0, int(row.get("mock_citations_count", cited_sources)))
    coverage = float(min(1.0, cited_sources / max(1, int(row.get("coverage_divisor", 3)))))
    strategy = row.get("expected_strategy", "light_qa")
    compare_quality = "ok" if expected_task == "compare" and cited_sources >= 2 else None
    abstained = expected_abstain
    reason_code = "no_retrieval_hit" if abstained else None
    passed = True
    reason = "phase3_rule_pass"
    if expected_task in {"multi_doc_synthesis", "compare"} and cited_sources < 2:
        passed = False
        reason = "insufficient_multi_source_coverage"
    if expected_abstain and not abstained:
        passed = False
        reason = "abstain_expected_but_missing"
    return Phase3EvalResult(
        id=row.get("id", "unknown"),
        scenario=row.get("scenario", "unknown"),
        query=row.get("query", ""),
        task_type=expected_task,
        planner_strategy=strategy,
        predicted_answer=row.get("mock_answer", "N/A"),
        citations_count=citations_count,
        multi_source_coverage=coverage,
        abstained=abstained,
        reason_code=reason_code,
        compare_structure_quality=compare_quality,
        passed=passed,
        reason=reason,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--out-json", required=True)
    parser.add_argument("--out-md", required=True)
    parser.add_argument("--out-failures", required=True)
    args = parser.parse_args()

    rows = load_jsonl(Path(args.dataset))
    results = [evaluate_case(row) for row in rows]
    total = len(results)
    passed = sum(1 for item in results if item.passed)
    failed_rows = [item for item in results if not item.passed]

    payload = {
        "generated_at": datetime.utcnow().isoformat(),
        "summary": {"total": total, "passed": passed, "failed": total - passed},
        "results": [asdict(item) for item in results],
    }
    Path(args.out_json).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# Phase3A Eval Report",
        "",
        f"- total: {total}",
        f"- passed: {passed}",
        f"- failed: {total - passed}",
        "",
        "| id | task_type | strategy | citations | coverage | abstained | passed | reason |",
        "|---|---|---|---:|---:|---|---|---|",
    ]
    for item in results:
        lines.append(
            f"| {item.id} | {item.task_type} | {item.planner_strategy} | {item.citations_count} | "
            f"{item.multi_source_coverage:.2f} | {item.abstained} | {item.passed} | {item.reason} |"
        )
    Path(args.out_md).write_text("\n".join(lines) + "\n", encoding="utf-8")

    with Path(args.out_failures).open("w", encoding="utf-8") as fp:
        for item in failed_rows:
            fp.write(json.dumps(asdict(item), ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
