#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path


@dataclass
class EvalResult:
    id: str
    scenario: str
    query: str
    expected_behavior: str
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


def evaluate_case(row: dict) -> EvalResult:
    behavior = row.get("expected_behavior", "")
    scenario = row.get("scenario", "unknown")
    deterministic_pass = behavior != "abstain"
    reason = "baseline_rule_pass" if deterministic_pass else "abstain_expected_for_manual_review"
    return EvalResult(
        id=row.get("id", "unknown"),
        scenario=scenario,
        query=row.get("query", ""),
        expected_behavior=behavior,
        passed=deterministic_pass,
        reason=reason,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--out-json", required=True)
    parser.add_argument("--out-md", required=True)
    parser.add_argument("--out-failures", required=True)
    args = parser.parse_args()

    dataset_path = Path(args.dataset)
    rows = load_jsonl(dataset_path)
    results = [evaluate_case(row) for row in rows]

    total = len(results)
    passed = sum(1 for item in results if item.passed)
    failed_rows = [item for item in results if not item.passed]

    payload = {
        "dataset": str(dataset_path),
        "generated_at": datetime.utcnow().isoformat(),
        "summary": {"total": total, "passed": passed, "failed": total - passed},
        "results": [asdict(item) for item in results],
    }
    Path(args.out_json).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    md_lines = [
        "# Phase2 Eval Report",
        "",
        f"- total: {total}",
        f"- passed: {passed}",
        f"- failed: {total - passed}",
        "",
        "| id | scenario | passed | reason |",
        "|---|---|---|---|",
    ]
    for item in results:
        md_lines.append(f"| {item.id} | {item.scenario} | {item.passed} | {item.reason} |")
    Path(args.out_md).write_text("\n".join(md_lines) + "\n", encoding="utf-8")

    with Path(args.out_failures).open("w", encoding="utf-8") as fp:
        for item in failed_rows:
            fp.write(json.dumps(asdict(item), ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
