from __future__ import annotations

"""
Minimal RAG eval: same JSONL samples with rerank off vs on via qa_service.ask_question (no HTTP).

Run from apps/api with DB + .env configured:
  python scripts/eval_rag.py --input samples.jsonl [--limit N] [--output report.json] [--rerank-top-n 20]
"""

import argparse
import json
import os
import sys
import time
from collections import Counter
from typing import Any

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from app.db.session import SessionLocal
from app.services.qa_service import QAServiceError, ask_question


def _default_output_path() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "eval_rag_report.json")


def _parse_sample(obj: dict[str, Any]) -> dict[str, Any]:
    if "question" not in obj or not str(obj["question"]).strip():
        raise ValueError("missing or empty 'question'")
    return {
        "question": str(obj["question"]).strip(),
        "scope_type": str(obj.get("scope_type", "all")),
        "folder_id": obj.get("folder_id"),
        "file_ids": obj.get("file_ids"),
        "strict_mode": bool(obj.get("strict_mode", False)),
        "expected_file_ids": obj.get("expected_file_ids"),
        "expected_chunk_ids": obj.get("expected_chunk_ids"),
        "expected_keywords": obj.get("expected_keywords"),
    }


def _load_jsonl(path: str, limit: int | None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with open(path, encoding="utf-8") as f:
        for line_no, raw in enumerate(f, start=1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ValueError(f"line {line_no}: invalid JSON: {exc}") from exc
            if not isinstance(obj, dict):
                raise ValueError(f"line {line_no}: expected object, got {type(obj).__name__}")
            rows.append(_parse_sample(obj))
            if limit is not None and len(rows) >= limit:
                break
    return rows


def _slim_refs(refs: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for r in refs or []:
        if not isinstance(r, dict):
            continue
        out.append(
            {
                "file_id": r.get("file_id"),
                "chunk_id": r.get("chunk_id"),
                "chunk_index": r.get("chunk_index"),
            }
        )
    return out


def _run_ask(
    db,
    sample: dict[str, Any],
    *,
    rerank_enabled: bool,
    rerank_top_n: int,
) -> dict[str, Any]:
    t0 = time.perf_counter()
    row: dict[str, Any] = {
        "ok": False,
        "latency_ms": 0.0,
        "error": None,
        "answer_source": None,
        "rerank_applied": None,
        "retrieval_meta": None,
        "refs_slim": [],
        "answer": "",
        "_raw_refs": [],
    }
    try:
        out = ask_question(
            db,
            question=sample["question"],
            scope_type=sample["scope_type"],
            folder_id=sample["folder_id"],
            file_ids=sample["file_ids"],
            strict_mode=sample["strict_mode"],
            top_k=6,
            candidate_k=None,
            max_context_chars=None,
            neighbor_window=None,
            dedupe_adjacent_chunks=None,
            rerank_enabled=rerank_enabled,
            rerank_top_n=rerank_top_n,
        )
        row["latency_ms"] = (time.perf_counter() - t0) * 1000
        meta = out.get("retrieval_meta") or {}
        refs = out.get("references") or []
        raw_list = refs if isinstance(refs, list) else []
        row["ok"] = True
        row["answer_source"] = out.get("answer_source")
        row["rerank_applied"] = bool(meta.get("rerank_applied"))
        row["retrieval_meta"] = dict(meta) if isinstance(meta, dict) else meta
        row["refs_slim"] = _slim_refs(raw_list)
        row["answer"] = out.get("answer", "") or ""
        row["_raw_refs"] = [r for r in raw_list if isinstance(r, dict)]
        return row
    except (QAServiceError, RuntimeError) as exc:
        row["latency_ms"] = (time.perf_counter() - t0) * 1000
        row["error"] = f"{type(exc).__name__}: {exc}"
        return row
    except Exception as exc:  # noqa: BLE001
        row["latency_ms"] = (time.perf_counter() - t0) * 1000
        row["error"] = f"{type(exc).__name__}: {exc}"
        return row


def _keyword_hit(answer: str, raw_refs: list[dict[str, Any]], keywords: list[str]) -> bool:
    parts = [answer.lower()]
    for r in raw_refs:
        parts.append(str(r.get("snippet") or "").lower())
        parts.append(str(r.get("file_name") or "").lower())
    haystack = "\n".join(parts)
    return all(k.lower() in haystack for k in keywords if k)


def _aggregate_round(
    samples: list[dict[str, Any]],
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    total = len(samples)
    answered = sum(1 for r in rows if r.get("ok"))
    src: Counter[str] = Counter()
    latencies: list[float] = []
    rerank_yes = 0

    file_eval = file_hits = 0
    chunk_eval = chunk_hits = 0
    recall_sum = 0.0
    recall_n = 0
    kw_eval = kw_hits = 0
    distinct_docs_topk_sum = 0.0
    distinct_docs_ctx_sum = 0.0
    same_doc_chunk_ratio_sum = 0.0
    adjacent_redundancy_sum = 0.0
    multi_source_answers = 0

    for sample, row in zip(samples, rows):
        if not row.get("ok"):
            continue
        src[str(row.get("answer_source") or "unknown")] += 1
        latencies.append(float(row["latency_ms"]))
        if row.get("rerank_applied"):
            rerank_yes += 1

        exp_files = sample.get("expected_file_ids")
        if exp_files:
            file_eval += 1
            got = {r["file_id"] for r in row["refs_slim"] if r.get("file_id") is not None}
            if got & set(exp_files):
                file_hits += 1

        exp_chunks = sample.get("expected_chunk_ids")
        if exp_chunks:
            chunk_eval += 1
            meta = row.get("retrieval_meta") or {}
            k = int(meta.get("top_k") or 6)
            ordered = [r["chunk_id"] for r in row["refs_slim"] if r.get("chunk_id") is not None]
            topk_set = set(ordered[:k])
            exp_set = set(exp_chunks)
            if topk_set & exp_set:
                chunk_hits += 1
            recall_sum += len(topk_set & exp_set) / max(1, len(exp_set))
            recall_n += 1

        exp_kw = sample.get("expected_keywords")
        if exp_kw:
            kw_eval += 1
            if _keyword_hit(str(row.get("answer") or ""), row.get("_raw_refs") or [], exp_kw):
                kw_hits += 1

        refs = [r for r in row["refs_slim"] if isinstance(r, dict)]
        file_ids = [r.get("file_id") for r in refs if r.get("file_id") is not None]
        if file_ids:
            distinct_docs = len(set(file_ids))
            distinct_docs_topk_sum += distinct_docs
            distinct_docs_ctx_sum += distinct_docs
            if distinct_docs >= 2:
                multi_source_answers += 1
            same_doc_chunk_ratio_sum += max(Counter(file_ids).values()) / max(1, len(file_ids))
            adjacent_pairs = 0
            adjacent_hits = 0
            by_file: dict[int, list[int]] = {}
            for r in refs:
                if r.get("file_id") is None or r.get("chunk_index") is None:
                    continue
                by_file.setdefault(int(r["file_id"]), []).append(int(r["chunk_index"]))
            for idxs in by_file.values():
                idxs.sort()
                for i in range(1, len(idxs)):
                    adjacent_pairs += 1
                    if abs(idxs[i] - idxs[i - 1]) <= 1:
                        adjacent_hits += 1
            adjacent_redundancy_sum += (adjacent_hits / adjacent_pairs) if adjacent_pairs else 0.0

    def _rate(num: int, den: int) -> float | None:
        if den <= 0:
            return None
        return num / den

    def _pct(values: list[float], p: float) -> float | None:
        if not values:
            return None
        vals = sorted(values)
        idx = int(round((len(vals) - 1) * p))
        return vals[max(0, min(idx, len(vals) - 1))]

    return {
        "total_questions": total,
        "answered_count": answered,
        "answer_source_distribution": dict(src),
        "avg_latency_ms": sum(latencies) / len(latencies) if latencies else None,
        "p50_latency_ms": _pct(latencies, 0.50),
        "p95_latency_ms": _pct(latencies, 0.95),
        "rerank_applied_rate": _rate(rerank_yes, answered) if answered else None,
        "retrieval_file_hit_rate": _rate(file_hits, file_eval),
        "retrieval_chunk_hit_rate": _rate(chunk_hits, chunk_eval),
        "recall_at_top_k_mean": (recall_sum / recall_n) if recall_n else None,
        "keyword_hit_rate": _rate(kw_hits, kw_eval),
        "distinct_docs_in_topk": (distinct_docs_topk_sum / answered) if answered else None,
        "distinct_docs_in_context": (distinct_docs_ctx_sum / answered) if answered else None,
        "same_doc_chunk_ratio": (same_doc_chunk_ratio_sum / answered) if answered else None,
        "adjacent_chunk_redundancy_rate": (adjacent_redundancy_sum / answered) if answered else None,
        "multi_source_answer_rate": _rate(multi_source_answers, answered) if answered else None,
        "_denoms": {
            "file_evaluated": file_eval,
            "chunk_evaluated": chunk_eval,
            "recall_evaluated": recall_n,
            "keyword_evaluated": kw_eval,
        },
    }


def _print_summary(label_a: str, m_a: dict[str, Any], label_b: str, m_b: dict[str, Any]) -> None:
    def fmt(x: Any) -> str:
        if x is None:
            return "n/a"
        if isinstance(x, float):
            return f"{x:.4f}"
        return str(x)

    print()
    print("=== RAG eval: rerank OFF vs ON ===")
    keys = [
        ("total_questions", "total_questions"),
        ("answered_count", "answered_count"),
        ("avg_latency_ms", "avg_latency_ms"),
        ("p50_latency_ms", "p50_latency_ms"),
        ("p95_latency_ms", "p95_latency_ms"),
        ("rerank_applied_rate", "rerank_applied_rate"),
        ("retrieval_file_hit_rate", "retrieval_file_hit_rate"),
        ("retrieval_chunk_hit_rate", "retrieval_chunk_hit_rate"),
        ("recall_at_top_k_mean", "recall@top_k_mean"),
        ("keyword_hit_rate", "keyword_hit_rate"),
        ("distinct_docs_in_context", "distinct_docs_in_context"),
        ("same_doc_chunk_ratio", "same_doc_chunk_ratio"),
        ("adjacent_chunk_redundancy_rate", "adjacent_chunk_redundancy_rate"),
        ("multi_source_answer_rate", "multi_source_answer_rate"),
    ]
    for key, title in keys:
        print(f"  {title}: {label_a}={fmt(m_a.get(key))} | {label_b}={fmt(m_b.get(key))}")
    print(f"  answer_source ({label_a}): {m_a.get('answer_source_distribution')}")
    print(f"  answer_source ({label_b}): {m_b.get('answer_source_distribution')}")
    print()


def _row_for_json(row: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in row.items() if not k.startswith("_")}


def main() -> int:
    parser = argparse.ArgumentParser(description="RAG eval: rerank off vs on (service layer).")
    parser.add_argument("--input", required=True, help="JSONL path")
    parser.add_argument("--limit", type=int, default=None, help="Max samples")
    parser.add_argument("--output", default=None, help="JSON report path")
    parser.add_argument("--rerank-top-n", type=int, default=20, help="rerank_top_n for both rounds")
    args = parser.parse_args()

    inp = os.path.abspath(args.input)
    out_path = os.path.abspath(args.output) if args.output else _default_output_path()
    rerank_top_n = max(1, int(args.rerank_top_n))

    try:
        samples = _load_jsonl(inp, args.limit)
    except (OSError, ValueError) as exc:
        print(f"Failed to load input: {exc}", file=sys.stderr)
        return 1

    if not samples:
        print("No samples loaded.", file=sys.stderr)
        return 1

    db = SessionLocal()
    round_off: list[dict[str, Any]] = []
    round_on: list[dict[str, Any]] = []
    try:
        for sample in samples:
            round_off.append(_run_ask(db, sample, rerank_enabled=False, rerank_top_n=rerank_top_n))
            round_on.append(_run_ask(db, sample, rerank_enabled=True, rerank_top_n=rerank_top_n))
    finally:
        db.close()

    m_off = _aggregate_round(samples, round_off)
    m_on = _aggregate_round(samples, round_on)
    _print_summary("rerank_off", m_off, "rerank_on", m_on)

    report = {
        "input": inp,
        "rerank_top_n": rerank_top_n,
        "round_a_rerank_off": {
            "metrics": {k: v for k, v in m_off.items() if not k.startswith("_")},
            "per_question": [_row_for_json(r) for r in round_off],
        },
        "round_b_rerank_on": {
            "metrics": {k: v for k, v in m_on.items() if not k.startswith("_")},
            "per_question": [_row_for_json(r) for r in round_on],
        },
    }
    try:
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"Wrote report: {out_path}")
    except OSError as exc:
        print(f"Failed to write report: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
