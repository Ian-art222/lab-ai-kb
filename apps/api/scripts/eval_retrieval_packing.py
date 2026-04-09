from __future__ import annotations

"""
检索 / packing / 多样化 对比评测：同一批问题分别跑「近似旧逻辑」与「当前配置」，输出结构化指标。

运行（需 DB + .env，在 apps/api 目录）:
  python scripts/eval_retrieval_packing.py \\
    --input evals/source_diversity_eval.sample.jsonl \\
    --output scripts/eval_retrieval_packing_report.json \\
    [--limit 5]

「旧逻辑」通过临时覆盖 Settings 关闭 parent 级多样化、MMR、parent Jaccard 去重与单文件 budget；
「新逻辑」使用当前环境变量 / .env 中的默认值（或你显式 export 的配置）。
"""

import argparse
import json
import os
import sys
import time
from collections import Counter
from typing import Any

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from app.core.config import settings as app_settings
from app.db.session import SessionLocal
from app.services.qa_service import QAServiceError, ask_question


def _load_jsonl(path: str, limit: int | None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
            if limit is not None and len(rows) >= limit:
                break
    return rows


def _snapshot_qa_pack_settings() -> dict[str, Any]:
    keys = [
        "qa_enable_diversification",
        "qa_enable_mmr_like_rerank",
        "qa_mmr_lambda",
        "qa_max_parents_per_file",
        "qa_max_parents_total",
        "qa_max_parents_per_heading",
        "qa_parent_similarity_dedup_threshold",
        "qa_same_heading_dedup",
        "qa_pack_per_file_budget_ratio",
        "qa_adjacent_parent_same_heading_only",
        "qa_debug_retrieval_trace_enabled",
        "qa_debug_store_intermediate_matches",
    ]
    return {k: getattr(app_settings, k) for k in keys}


def _apply_qa_pack_settings(overrides: dict[str, Any]) -> None:
    for k, v in overrides.items():
        setattr(app_settings, k, v)


def _reference_metrics(refs: list[dict[str, Any]] | None) -> dict[str, Any]:
    refs = refs or []
    by_file: Counter[int] = Counter()
    heading_keys: set[tuple[int, str]] = set()
    adjacent_hits = 0
    roles: Counter[str] = Counter()
    for r in refs:
        try:
            fid = int(r.get("file_id", 0))
        except (TypeError, ValueError):
            continue
        by_file[fid] += 1
        hp = r.get("heading_path")
        if hp is not None and str(hp).strip():
            heading_keys.add((fid, str(hp).strip()))
        if r.get("adjacent_expansion"):
            adjacent_hits += 1
        cr = r.get("context_chunk_role")
        if cr:
            roles[str(cr)] += 1
    n = len(refs)
    dom = (max(by_file.values()) / n) if n and by_file else 0.0
    return {
        "reference_count": n,
        "distinct_files_in_refs": len(by_file),
        "distinct_heading_keys": len(heading_keys),
        "dominant_file_ratio_in_refs": round(dom, 4),
        "adjacent_expansion_hits": adjacent_hits,
        "context_chunk_role_counts": dict(roles),
    }


def _run_once(
    db,
    row: dict[str, Any],
    *,
    rerank_enabled: bool,
) -> dict[str, Any]:
    q = str(row.get("question", "")).strip()
    out: dict[str, Any] = {
        "ok": False,
        "error": None,
        "answer_source": None,
        "refs_metrics": {},
        "retrieval_trace_keys": [],
        "latency_ms": 0.0,
    }
    t0 = time.perf_counter()
    try:
        res = ask_question(
            db,
            question=q,
            scope_type="all",
            folder_id=None,
            file_ids=None,
            strict_mode=bool(row.get("strict", row.get("strict_mode", True))),
            top_k=6,
            rerank_enabled=rerank_enabled,
        )
        out["latency_ms"] = (time.perf_counter() - t0) * 1000
        out["ok"] = True
        refs = res.get("references") or []
        meta = res.get("retrieval_meta") or {}
        trace = meta.get("retrieval_trace")
        out["answer_source"] = res.get("answer_source")
        out["refs_metrics"] = _reference_metrics(refs if isinstance(refs, list) else [])
        out["retrieval_meta_summary"] = {
            "packed_chunks": meta.get("packed_chunks"),
            "context_chars": meta.get("context_chars"),
            "source_count": meta.get("source_count"),
            "dominant_source_ratio": meta.get("dominant_source_ratio"),
            "adjacent_chunk_redundancy_rate": meta.get("adjacent_chunk_redundancy_rate"),
        }
        if isinstance(trace, dict):
            out["retrieval_trace_keys"] = sorted(trace.keys())
            out["pack_diversification"] = trace.get("pack_diversification")
            out["packing_summary"] = trace.get("packing")
    except QAServiceError as exc:
        out["latency_ms"] = (time.perf_counter() - t0) * 1000
        out["error"] = {"code": exc.code, "message": exc.message}
    except Exception as exc:
        out["latency_ms"] = (time.perf_counter() - t0) * 1000
        out["error"] = {"code": "UNEXPECTED", "message": str(exc)}
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="JSONL with question / strict fields")
    parser.add_argument("--output", default="", help="Write full JSON report")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--rerank", action="store_true", help="Enable rerank (default off for speed)")
    args = parser.parse_args()
    rows = _load_jsonl(args.input, args.limit)
    rerank = bool(args.rerank)
    baseline = _snapshot_qa_pack_settings()
    legacy_overrides = {
        "qa_enable_diversification": False,
        "qa_enable_mmr_like_rerank": False,
        "qa_parent_similarity_dedup_threshold": 0.99,
        "qa_pack_per_file_budget_ratio": 1.0,
        "qa_same_heading_dedup": False,
        "qa_adjacent_parent_same_heading_only": False,
        "qa_debug_retrieval_trace_enabled": True,
        "qa_debug_store_intermediate_matches": True,
    }

    report: dict[str, Any] = {
        "input": os.path.abspath(args.input),
        "baseline_settings": baseline,
        "legacy_overrides": legacy_overrides,
        "rows": [],
    }

    with SessionLocal() as db:
        for row in rows:
            rid = row.get("id")
            # Legacy-like
            _apply_qa_pack_settings(legacy_overrides)
            legacy_res = _run_once(db, row, rerank_enabled=rerank)
            # Restore then current
            _apply_qa_pack_settings(baseline)
            new_res = _run_once(db, row, rerank_enabled=rerank)

            lm = legacy_res.get("refs_metrics") or {}
            nm = new_res.get("refs_metrics") or {}
            report["rows"].append(
                {
                    "id": rid,
                    "question": row.get("question"),
                    "scenario_tags": row.get("scenario_tags"),
                    "legacy": legacy_res,
                    "new": new_res,
                    "delta": {
                        "distinct_files": (nm.get("distinct_files_in_refs") or 0)
                        - (lm.get("distinct_files_in_refs") or 0),
                        "distinct_headings": (nm.get("distinct_heading_keys") or 0)
                        - (lm.get("distinct_heading_keys") or 0),
                        "dominant_file_ratio_in_refs": round(
                            float(nm.get("dominant_file_ratio_in_refs") or 0)
                            - float(lm.get("dominant_file_ratio_in_refs") or 0),
                            4,
                        ),
                        "reference_count": (nm.get("reference_count") or 0) - (lm.get("reference_count") or 0),
                    },
                }
            )

    out_path = args.output or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "eval_retrieval_packing_report.json"
    )
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
