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
    selected_skill: str
    selected_scope: str
    planner_strategy: str
    retrieval_rounds: int
    fallback_triggered: bool
    clarify_triggered: bool
    source_count: int
    dominant_source_ratio: float
    multi_source_coverage: float
    predicted_answer: str
    citations_count: int
    abstained: bool
    reason_code: str | None
    compare_bucketed: bool
    guardrail_triggered: bool
    passed: bool
    reason: str


def load_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open("r", encoding="utf-8") as fp:
        for line in fp:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def evaluate_case(row: dict) -> Phase3EvalResult:
    task_type = row.get("expected_task_type", "simple_qa")
    selected_skill = row.get("expected_skill", "qa_skill")
    selected_scope = row.get("expected_scope", "default_kb_scope")
    strategy = row.get("expected_strategy", "single_pass_qa")
    source_count = max(0, int(row.get("mock_source_count", 1)))
    citations_count = max(0, int(row.get("mock_citations_count", source_count)))
    dominant_source_ratio = float(row.get("mock_dominant_source_ratio", 1.0 if source_count <= 1 else 0.6))
    multi_source_coverage = float(row.get("mock_multi_source_coverage", min(1.0, source_count / 3)))
    clarify_triggered = bool(row.get("expected_clarify", False))
    fallback_triggered = bool(row.get("expected_fallback", False))
    retrieval_rounds = 2 if fallback_triggered else 1
    abstained = bool(row.get("should_abstain", False))
    reason_code = row.get("expected_reason_code") or ("insufficient_evidence" if abstained else None)
    compare_bucketed = bool(row.get("expected_compare_bucketed", task_type == "compare"))
    guardrail_triggered = bool(row.get("expected_guardrail", False))

    passed = True
    reason = "phase3b_rule_pass"
    if task_type in {"multi_doc_synthesis", "compare"} and source_count < 2 and not abstained:
        passed = False
        reason = "insufficient_multi_source_coverage"
    if clarify_triggered and task_type != "clarification_needed":
        passed = False
        reason = "clarify_signal_mismatch"
    if fallback_triggered and retrieval_rounds < 2:
        passed = False
        reason = "fallback_round_missing"

    return Phase3EvalResult(
        id=row.get("id", "unknown"),
        scenario=row.get("scenario", "unknown"),
        query=row.get("query", ""),
        task_type=task_type,
        selected_skill=selected_skill,
        selected_scope=selected_scope,
        planner_strategy=strategy,
        retrieval_rounds=retrieval_rounds,
        fallback_triggered=fallback_triggered,
        clarify_triggered=clarify_triggered,
        source_count=source_count,
        dominant_source_ratio=dominant_source_ratio,
        multi_source_coverage=multi_source_coverage,
        predicted_answer=row.get("mock_answer", "N/A"),
        citations_count=citations_count,
        abstained=abstained,
        reason_code=reason_code,
        compare_bucketed=compare_bucketed,
        guardrail_triggered=guardrail_triggered,
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
        "# Phase3B Eval Report",
        "",
        f"- total: {total}",
        f"- passed: {passed}",
        f"- failed: {total - passed}",
        "",
        "| id | task | skill | scope | strategy | rounds | fallback | clarify | src_count | dom_ratio | coverage | citations | abstained | reason |",
        "|---|---|---|---|---|---:|---|---|---:|---:|---:|---:|---|---|",
    ]
    for item in results:
        lines.append(
            f"| {item.id} | {item.task_type} | {item.selected_skill} | {item.selected_scope} | {item.planner_strategy} | "
            f"{item.retrieval_rounds} | {item.fallback_triggered} | {item.clarify_triggered} | {item.source_count} | "
            f"{item.dominant_source_ratio:.2f} | {item.multi_source_coverage:.2f} | {item.citations_count} | {item.abstained} | {item.reason} |"
        )
    Path(args.out_md).write_text("\n".join(lines) + "\n", encoding="utf-8")

    with Path(args.out_failures).open("w", encoding="utf-8") as fp:
        for item in failed_rows:
            fp.write(json.dumps(asdict(item), ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
