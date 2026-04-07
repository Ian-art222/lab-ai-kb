from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


def _load_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open("r", encoding="utf-8") as f:
        for raw in f:
            raw = raw.strip()
            if not raw:
                continue
            rows.append(json.loads(raw))
    return rows


def _multi_source_coverage(sources: list[int]) -> bool:
    return len(set(sources or [])) >= 2


def run_eval(dataset_path: Path, prediction_path: Path, report_json: Path, report_md: Path, failure_jsonl: Path) -> dict:
    dataset = {row["id"]: row for row in _load_jsonl(dataset_path)}
    preds = _load_jsonl(prediction_path)
    out_rows: list[dict] = []
    cat = Counter()
    abstains = 0
    multi_source_hits = 0
    for p in preds:
        did = p["id"]
        d = dataset.get(did, {})
        coverage = _multi_source_coverage(p.get("retrieved_sources", []))
        row = {
            "id": did,
            "query": p.get("query") or d.get("query"),
            "expected_behavior": d.get("expected_behavior"),
            "predicted_answer": p.get("predicted_answer"),
            "abstained": bool(p.get("abstained")),
            "abstain_reason": p.get("abstain_reason"),
            "retrieved_sources": p.get("retrieved_sources", []),
            "citation_count": int(p.get("citation_count", 0)),
            "multi_source_coverage": coverage,
            "latency_ms": float(p.get("latency_ms", 0.0)),
        }
        out_rows.append(row)
        cat[d.get("category", "unknown")] += 1
        if row["abstained"]:
            abstains += 1
        if coverage:
            multi_source_hits += 1

    summary = {
        "total": len(out_rows),
        "abstain_rate": (abstains / len(out_rows)) if out_rows else 0.0,
        "multi_source_coverage_rate": (multi_source_hits / len(out_rows)) if out_rows else 0.0,
        "category_distribution": dict(cat),
    }
    report = {"summary": summary, "rows": out_rows}
    report_json.parent.mkdir(parents=True, exist_ok=True)
    report_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    md_lines = [
        "# Phase2 Eval Report",
        "",
        f"- total: {summary['total']}",
        f"- abstain_rate: {summary['abstain_rate']:.2%}",
        f"- multi_source_coverage_rate: {summary['multi_source_coverage_rate']:.2%}",
        "",
    ]
    report_md.write_text("\n".join(md_lines), encoding="utf-8")

    failure_jsonl.parent.mkdir(parents=True, exist_ok=True)
    with failure_jsonl.open("w", encoding="utf-8") as f:
        for row in out_rows:
            if row["abstained"] or row["citation_count"] <= 1:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="evals/datasets/phase2_regression.sample.jsonl")
    parser.add_argument("--predictions", default="evals/fixtures/phase2_predictions.sample.jsonl")
    parser.add_argument("--out-json", default="evals/reports/phase2_eval_report.json")
    parser.add_argument("--out-md", default="evals/reports/phase2_eval_report.md")
    parser.add_argument("--failure-out", default="evals/reports/phase2_failure_cases.jsonl")
    args = parser.parse_args()
    run_eval(
        dataset_path=Path(args.dataset),
        prediction_path=Path(args.predictions),
        report_json=Path(args.out_json),
        report_md=Path(args.out_md),
        failure_jsonl=Path(args.failure_out),
    )


if __name__ == "__main__":
    main()

