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
    clarification_needed: bool
    guardrail_events: list[str]
    source_count: int
    dominant_source_ratio: float
    multi_source_coverage: float
    compare_symmetry: float | None
    evidence_asymmetry: bool | None
    abstained: bool
    reason_code: str | None
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
    dominant_source_ratio = float(row.get("mock_dominant_source_ratio", 1.0 if source_count <= 1 else 0.6))
    multi_source_coverage = float(row.get("mock_multi_source_coverage", min(1.0, source_count / 3)))
    clarification_needed = bool(row.get("expected_clarify", False))
    fallback_triggered = bool(row.get("expected_fallback", False))
    retrieval_rounds = int(row.get("mock_retrieval_rounds", 2 if fallback_triggered else 1))
    abstained = bool(row.get("should_abstain", False))
    reason_code = row.get("expected_reason_code") or ("insufficient_evidence" if abstained else None)
    guardrail_events = row.get("expected_guardrail_events", ["input_guardrail"] if row.get("expected_guardrail") else [])
    compare_symmetry = row.get("mock_compare_symmetry")
    evidence_asymmetry = row.get("mock_evidence_asymmetry")

    passed = True
    reason = "phase4_rule_pass"

    if task_type in {"multi_doc_synthesis", "compare"} and not clarification_needed:
        if source_count < 2 and not abstained:
            passed = False
            reason = "insufficient_multi_source_coverage"
        if dominant_source_ratio > 0.82 and not abstained:
            passed = False
            reason = "dominance_not_handled"

    if clarification_needed and task_type != "clarification_needed":
        passed = False
        reason = "clarification_boundary_mismatch"

    if fallback_triggered and retrieval_rounds < 2:
        passed = False
        reason = "fallback_round_missing"

    if row.get("expected_guardrail") and not guardrail_events:
        passed = False
        reason = "guardrail_event_missing"

    if task_type == "compare" and compare_symmetry is not None and compare_symmetry < 0.6 and not abstained:
        if not bool(evidence_asymmetry):
            passed = False
            reason = "compare_asymmetry_not_flagged"

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
        clarification_needed=clarification_needed,
        guardrail_events=guardrail_events,
        source_count=source_count,
        dominant_source_ratio=dominant_source_ratio,
        multi_source_coverage=multi_source_coverage,
        compare_symmetry=float(compare_symmetry) if compare_symmetry is not None else None,
        evidence_asymmetry=bool(evidence_asymmetry) if evidence_asymmetry is not None else None,
        abstained=abstained,
        reason_code=reason_code,
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
        "# Phase4 Eval Report",
        "",
        f"- total: {total}",
        f"- passed: {passed}",
        f"- failed: {total - passed}",
        "",
        "| id | task | scope | skill | rounds | fallback | clarify | guardrails | src_count | dom_ratio | coverage | symmetry | asym | abstained | reason |",
        "|---|---|---|---|---:|---|---|---|---:|---:|---:|---:|---|---|---|",
    ]
    for item in results:
        lines.append(
            f"| {item.id} | {item.task_type} | {item.selected_scope} | {item.selected_skill} | {item.retrieval_rounds} | "
            f"{item.fallback_triggered} | {item.clarification_needed} | {','.join(item.guardrail_events) or '-'} | {item.source_count} | "
            f"{item.dominant_source_ratio:.2f} | {item.multi_source_coverage:.2f} | {item.compare_symmetry if item.compare_symmetry is not None else '-'} | "
            f"{item.evidence_asymmetry if item.evidence_asymmetry is not None else '-'} | {item.abstained} | {item.reason} |"
        )
    Path(args.out_md).write_text("\n".join(lines) + "\n", encoding="utf-8")

    with Path(args.out_failures).open("w", encoding="utf-8") as fp:
        for item in failed_rows:
            fp.write(json.dumps(asdict(item), ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
