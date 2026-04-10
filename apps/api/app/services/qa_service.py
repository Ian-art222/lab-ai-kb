from __future__ import annotations

import logging
import math
import re
import time
import uuid
from collections import defaultdict
from datetime import datetime
from typing import Any

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.core.config import settings as app_settings
from app.models.file_record import FileRecord
from app.models.folder import Folder
from app.models.knowledge import KnowledgeChunk, QACitation, QAMessage, QARetrievalTrace, QASession
from app.models.system_setting import SystemSetting
from app.models.user import User
from app.services.failure_cases import build_failure_case, sink_failure_case
from app.services.model_service import chat_completion, embed_texts
from app.services.qa_agent_workflow import (
    TASK_ABSTAIN,
    TASK_CLARIFICATION_NEEDED,
    TASK_COLLECTION_SCOPED_QA,
    TASK_COMPARE,
    TASK_MULTI_DOC_SYNTHESIS,
    build_session_context,
    plan_retrieval,
    route_task_scope_skill,
    summarize_tool_trace,
)
from app.services.context_packing import (
    build_coverage_diagnostics_payload,
    min_distinct_files_for_query_type,
    rank_files_by_context_chars,
    resolve_pack_provenance,
    select_pack_items_coverage_two_phase,
)
from app.services.qa_guardrails import (
    apply_evidence_guardrail,
    apply_input_guardrail,
    apply_output_guardrail,
    assess_coverage_sufficiency_for_answer,
    assess_evidence_sufficiency,
    evidence_conflict_hint,
)
from app.services.qa_synthesis import build_answer_synthesis_addon
from app.services.query_understanding import build_query_analysis, compact_query_trace_for_meta
from app.services.reason_codes import QAReasonCode, normalize_reason_code
from app.services.settings_service import build_embedding_index_standard

MIN_SIMILARITY_SCORE = 0.25
MIN_HYBRID_RRF_SCORE = 0.012
MAX_TOP_K = 8
MIN_TOP_K = 1
MIN_RETRIEVAL_CHUNK_CHARS = 60
SNIPPET_TRUNCATE_LENGTH = 220

logger = logging.getLogger(__name__)

DEFAULT_RETRIEVAL_STRATEGY = "app_layer_cosine_topk"


COVERAGE_POLICY = {
    "synthesis": {
        "min_source_count": 2,
        "max_dominant_source_ratio": 0.72,
        "min_multi_source_coverage": 0.67,
    },
    "compare": {
        "min_source_count": 2,
        "max_dominant_source_ratio": 0.65,
        "min_multi_source_coverage": 0.67,
        "max_asymmetry_ratio": 0.7,
    },
    "default": {
        "min_source_count": 1,
        "max_dominant_source_ratio": 0.82,
        "min_multi_source_coverage": 0.34,
    },
}


def _coverage_policy_for_task(task_type: str) -> dict[str, float]:
    if task_type == TASK_COMPARE:
        return COVERAGE_POLICY["compare"]
    if task_type == TASK_MULTI_DOC_SYNTHESIS:
        return COVERAGE_POLICY["synthesis"]
    return COVERAGE_POLICY["default"]


def _evaluate_coverage_decision(*, task_type: str, metrics: dict[str, float | int], retrieval_rounds: int, max_rounds: int) -> dict[str, Any]:
    policy = _coverage_policy_for_task(task_type)
    source_count = int(metrics.get("source_count") or 0)
    dom_ratio = float(metrics.get("dominant_source_ratio") or 0.0)
    coverage = float(metrics.get("multi_source_coverage") or 0.0)

    insufficient = source_count < policy["min_source_count"] or coverage < policy["min_multi_source_coverage"]
    skewed = dom_ratio > policy["max_dominant_source_ratio"]

    action = "answer"
    if insufficient and retrieval_rounds < max_rounds:
        action = "fallback"
    elif insufficient and retrieval_rounds >= max_rounds:
        action = "abstain"
    elif skewed and task_type in {TASK_COMPARE, TASK_MULTI_DOC_SYNTHESIS}:
        action = "conservative_answer"

    return {
        "policy": policy,
        "insufficient": insufficient,
        "single_source_skew": skewed,
        "action": action,
    }

# Upper bound for in-memory ranked pool (top_k vs qa_candidate_k); avoids unbounded scans.
QA_RETRIEVAL_POOL_CAP = 128


def _normalize_retrieval_mode(value: str | None) -> str:
    mode = (value or "").strip().lower()
    if mode in {"semantic", "lexical", "hybrid"}:
        return mode
    return "hybrid"


def _score_threshold_for_mode(mode: str) -> float:
    if mode == "semantic":
        return float(app_settings.qa_semantic_threshold)
    if mode == "lexical":
        return float(app_settings.qa_lexical_threshold)
    return float(app_settings.qa_hybrid_threshold)


def _build_query_variants(question: str) -> list[str]:
    base = " ".join((question or "").split()).strip()
    if not base:
        return []
    if not app_settings.qa_query_expansion_enabled:
        return [base]

    variants: list[str] = [base]
    compact = re.sub(r"[^\w\u4e00-\u9fff]+", " ", base, flags=re.UNICODE).strip()
    if compact and compact != base:
        variants.append(compact)

    # Keep high-signal words as a lexical-biased variant.
    tokens = [tok for tok in compact.split() if len(tok) >= 2]
    if len(tokens) >= 3:
        variants.append(" ".join(tokens[:12]))

    max_q = max(1, int(app_settings.qa_query_expansion_max_queries))
    out: list[str] = []
    seen: set[str] = set()
    for q in variants:
        nq = q.strip()
        if not nq or nq in seen:
            continue
        seen.add(nq)
        out.append(nq)
        if len(out) >= max_q:
            break
    return out or [base]


def _child_or_legacy_retrieval_filter():
    """Recall child rows; NULL chunk_kind keeps legacy chunks indexed before parent-child."""
    return or_(KnowledgeChunk.chunk_kind == "child", KnowledgeChunk.chunk_kind.is_(None))


def _build_retrieval_meta(
    *,
    retrieval_strategy: str,
    answer_source: str,
    scope_type: str,
    strict_mode: bool,
    top_k: int,
    compatible_file_count: int,
    candidate_chunks: int,
    matched_chunks: int,
    selected_chunks: int,
    used_file_ids: list[int],
    candidate_k: int,
    expanded_chunks: int,
    packed_chunks: int,
    context_chars: int,
    neighbor_window: int,
    dedupe_adjacent_chunks: bool,
    retrieval_mode: str,
    semantic_candidate_count: int,
    lexical_candidate_count: int,
    fusion_method: str,
    score_threshold_applied: float,
    rerank_enabled: bool,
    rerank_input_count: int,
    rerank_output_count: int,
    rerank_model_name: str,
    rerank_applied: bool,
    parent_recovered_chunks: int = 0,
    parent_deduped_groups: int = 0,
    distinct_docs_in_topk: int = 0,
    distinct_docs_in_context: int = 0,
    same_doc_chunk_ratio: float = 0.0,
    adjacent_chunk_redundancy_rate: float = 0.0,
    dominance_guardrail_triggered: bool = False,
    diversity_rerank_enabled: bool = False,
    diversity_rerank_applied: bool = False,
    diversity_rerank_fetch_k: int = 0,
    normalized_query: str | None = None,
    rewritten_queries: list[str] | None = None,
    abstain_reason: str | None = None,
    abstain_reason_code: str | None = None,
    failure_reason_code: str | None = None,
    trace_id: str | None = None,
    request_id: str | None = None,
    task_type: str | None = None,
    planner_output: dict | None = None,
    selected_strategy: str | None = None,
    workflow_steps_json: list | None = None,
    tool_traces_json: list | None = None,
    session_context_json: dict | None = None,
    final_answer_type: str | None = None,
    selected_scope: str | None = None,
    selected_skill: str | None = None,
    planner_meta: dict | None = None,
    compare_result: dict | None = None,
    clarification_needed: bool | None = None,
    workflow_summary: str | None = None,
    source_count: int | None = None,
    dominant_source_ratio: float | None = None,
    multi_source_coverage: float | None = None,
    fallback_triggered: bool | None = None,
    retrieval_rounds: int | None = None,
    stop_reason: str | None = None,
    retrieval_trace: dict | None = None,
    query_understanding_summary: dict | None = None,
    answer_synthesis_trace: dict | None = None,
    coverage_diagnostics: dict | None = None,
) -> dict:
    """Normalized retrieval_meta for API responses; keeps legacy min_score alongside min_similarity_score."""
    meta = {
        "retrieval_strategy": retrieval_strategy or DEFAULT_RETRIEVAL_STRATEGY,
        "answer_source": answer_source,
        "scope_type": scope_type,
        "strict_mode": strict_mode,
        "top_k": top_k,
        "min_similarity_score": score_threshold_applied,
        "candidate_chunks": candidate_chunks,
        "matched_chunks": matched_chunks,
        # Final chunks actually concatenated into the LLM context (same as packed_chunks when packing runs).
        "selected_chunks": selected_chunks,
        "compatible_file_count": compatible_file_count,
        "used_file_ids": used_file_ids,
        # Legacy field name (same value as min_similarity_score)
        "min_score": score_threshold_applied,
        "candidate_k": candidate_k,
        "expanded_chunks": expanded_chunks,
        "packed_chunks": packed_chunks,
        "context_chars": context_chars,
        "neighbor_window": neighbor_window,
        "dedupe_adjacent_chunks": dedupe_adjacent_chunks,
        "retrieval_mode": retrieval_mode,
        "semantic_candidate_count": semantic_candidate_count,
        "lexical_candidate_count": lexical_candidate_count,
        "fusion_method": fusion_method,
        "score_threshold_applied": score_threshold_applied,
        "rerank_enabled": rerank_enabled,
        "rerank_input_count": rerank_input_count,
        "rerank_output_count": rerank_output_count,
        "rerank_model_name": rerank_model_name,
        "rerank_applied": rerank_applied,
        "parent_recovered_chunks": parent_recovered_chunks,
        "parent_deduped_groups": parent_deduped_groups,
        "distinct_docs_in_topk": distinct_docs_in_topk,
        "distinct_docs_in_context": distinct_docs_in_context,
        "same_doc_chunk_ratio": same_doc_chunk_ratio,
        "adjacent_chunk_redundancy_rate": adjacent_chunk_redundancy_rate,
        "dominance_guardrail_triggered": dominance_guardrail_triggered,
        "diversity_rerank_enabled": diversity_rerank_enabled,
        "diversity_rerank_applied": diversity_rerank_applied,
        "diversity_rerank_fetch_k": diversity_rerank_fetch_k,
        "normalized_query": normalized_query,
        "rewritten_queries": rewritten_queries or [],
        "abstain_reason": abstain_reason,
        "abstain_reason_code": abstain_reason_code,
        "failure_reason_code": failure_reason_code,
        "trace_id": trace_id,
        "request_id": request_id,
        "task_type": task_type,
        "planner_output": planner_output or {},
        "selected_strategy": selected_strategy,
        "workflow_steps_json": workflow_steps_json or [],
        "tool_traces_json": tool_traces_json or [],
        "session_context_json": session_context_json or {},
        "final_answer_type": final_answer_type,
        "selected_scope": selected_scope,
        "selected_skill": selected_skill,
        "planner_meta": planner_meta or {},
        "compare_result": compare_result,
        "clarification_needed": clarification_needed,
        "workflow_summary": workflow_summary,
        "source_count": source_count,
        "dominant_source_ratio": dominant_source_ratio,
        "multi_source_coverage": multi_source_coverage,
        "fallback_triggered": fallback_triggered,
        "retrieval_rounds": retrieval_rounds,
        "stop_reason": stop_reason,
    }
    if retrieval_trace:
        meta["retrieval_trace"] = retrieval_trace
    if query_understanding_summary:
        meta["query_understanding"] = query_understanding_summary
    if answer_synthesis_trace:
        meta["answer_synthesis"] = answer_synthesis_trace
    if coverage_diagnostics is not None:
        meta["coverage_diagnostics"] = coverage_diagnostics
    return meta


def _truncate_ranked_to_candidate_k(ranked: list[dict], candidate_k: int) -> list[dict]:
    """Take the first candidate_k items from an already score-sorted ranked list."""
    if candidate_k < 1:
        return []
    return ranked[:candidate_k]


def _is_grounded_answer(answer: str, references: list[dict]) -> bool:
    text = (answer or "").strip()
    if not text:
        return False
    if not references:
        return False
    return True


def _neighbor_score_from_seed(seed_score: float, index_distance: int) -> float:
    if index_distance <= 0:
        return seed_score
    return seed_score * (0.01 / (1 + abs(index_distance)))


def _score_neighbor_chunk(chunk: KnowledgeChunk, seeds: list[dict]) -> float:
    best = 0.0
    for item in seeds:
        sch = item["chunk"]
        if sch.file_id != chunk.file_id:
            continue
        dist = abs(chunk.chunk_index - sch.chunk_index)
        s = _neighbor_score_from_seed(item["score"], dist)
        if s > best:
            best = s
    return best


def _expand_neighbor_chunks(db: Session, seeds: list[dict], neighbor_window: int) -> list[dict]:
    """Load same-file chunks within ±neighbor_window of each seed chunk_index; seeds keep original scores."""
    if neighbor_window <= 0 or not seeds:
        for item in seeds:
            item.setdefault("source_reason", "retrieval_hit")
        return list(seeds)

    needed: dict[int, set[int]] = {}
    seed_ids = {item["chunk"].id for item in seeds}
    for item in seeds:
        ch = item["chunk"]
        lo = max(0, ch.chunk_index - neighbor_window)
        hi = ch.chunk_index + neighbor_window
        needed.setdefault(ch.file_id, set()).update(range(lo, hi + 1))

    by_id: dict[int, dict] = {}
    for item in seeds:
        merged = dict(item)
        merged.setdefault("source_reason", "retrieval_hit")
        by_id[item["chunk"].id] = merged

    for file_id, idxs in needed.items():
        rows = (
            db.query(KnowledgeChunk, FileRecord.file_name, FileRecord.folder_id)
            .join(FileRecord, KnowledgeChunk.file_id == FileRecord.id)
            .filter(KnowledgeChunk.file_id == file_id, KnowledgeChunk.chunk_index.in_(idxs))
            .filter(_child_or_legacy_retrieval_filter())
            .all()
        )
        for chunk, file_name, folder_id in rows:
            if chunk.id in by_id:
                continue
            best_seed: dict | None = None
            best_s = -1.0
            for sitem in seeds:
                sch = sitem["chunk"]
                if sch.file_id != chunk.file_id:
                    continue
                dist = abs(chunk.chunk_index - sch.chunk_index)
                sc = _neighbor_score_from_seed(float(sitem["score"]), dist)
                if sc > best_s:
                    best_s = sc
                    best_seed = sitem
            by_id[chunk.id] = {
                "chunk": chunk,
                "file_name": file_name,
                "folder_id": folder_id,
                "score": _score_neighbor_chunk(chunk, seeds),
                "source": "semantic",
                "source_reason": "neighbor_expansion",
                "matched_query_index": int(best_seed.get("matched_query_index", -1)) if best_seed else -1,
            }

    seed_order = [item["chunk"].id for item in seeds]
    rest = [cid for cid in by_id if cid not in seed_ids]
    rest_sorted = sorted(
        rest,
        key=lambda cid: (by_id[cid]["chunk"].file_id, by_id[cid]["chunk"].chunk_index),
    )
    ordered_ids = seed_order + rest_sorted
    return [by_id[cid] for cid in ordered_ids if cid in by_id]


def _cap_children_per_parent(items: list[dict], max_n: int) -> list[dict]:
    """同一 parent 下最多保留 max_n 条子 chunk（按输入顺序中高分已在前时可先排序）。"""
    max_n = max(1, int(max_n))
    counts: dict[tuple[int, int], int] = defaultdict(int)
    out: list[dict] = []
    for it in items:
        ch = it["chunk"]
        pid = getattr(ch, "parent_chunk_id", None)
        if pid is None:
            out.append(it)
            continue
        key = (int(ch.file_id), int(pid))
        if counts[key] >= max_n:
            continue
        counts[key] += 1
        out.append(it)
    return out


def _want_packing_trace_dict() -> bool:
    """为 coverage diagnostics / 调试收集 per-file 字符等 packing 统计。"""
    return bool(
        app_settings.qa_debug_retrieval_trace_enabled
        or app_settings.qa_enable_coverage_diagnostics
        or app_settings.qa_packing_trace_enabled
    )


def _dedupe_chunk_items(items: list[dict]) -> list[dict]:
    """Deduplicate by chunk.id; on conflict keep the highest score; preserve first-seen order."""
    best: dict[int, dict] = {}
    order: list[int] = []
    for item in items:
        cid = item["chunk"].id
        if cid not in best:
            best[cid] = item
            order.append(cid)
        elif item["score"] > best[cid]["score"]:
            best[cid] = item
    return [best[cid] for cid in order]


def _doc_key(item: dict) -> int:
    return int(item["chunk"].file_id)


def _normalize_text_for_similarity(text: str) -> set[str]:
    compact = re.sub(r"\s+", " ", (text or "").strip().lower())
    return {tok for tok in re.split(r"[^\w\u4e00-\u9fff]+", compact) if tok}


def _text_jaccard_similarity(a: str, b: str) -> float:
    sa = _normalize_text_for_similarity(a)
    sb = _normalize_text_for_similarity(b)
    if not sa or not sb:
        return 0.0
    inter = len(sa & sb)
    union = len(sa | sb)
    if union == 0:
        return 0.0
    return inter / union


def _diversity_rerank_matches(
    matches: list[dict],
    *,
    enabled: bool,
    diversity_lambda: float,
    fetch_k: int,
    redundancy_sim_threshold: float,
) -> tuple[list[dict], bool]:
    if not enabled or len(matches) <= 1:
        return list(matches), False

    k = max(1, min(fetch_k, len(matches)))
    lam = max(0.0, min(1.0, diversity_lambda))
    pool = list(matches[:k])
    selected: list[dict] = []

    while pool:
        if not selected:
            best_idx = 0
        else:
            best_idx = 0
            best_score = -10**9
            for idx, item in enumerate(pool):
                rel = float(item.get("rerank_score", item.get("score", 0.0)))
                penalties = []
                for chosen in selected:
                    same_doc = 1.0 if _doc_key(chosen) == _doc_key(item) else 0.0
                    sim = _text_jaccard_similarity(chosen["chunk"].content or "", item["chunk"].content or "")
                    if sim < redundancy_sim_threshold:
                        sim = 0.0
                    penalties.append(max(same_doc, sim))
                penalty = max(penalties) if penalties else 0.0
                mmr_score = lam * rel - (1.0 - lam) * penalty
                if mmr_score > best_score:
                    best_score = mmr_score
                    best_idx = idx
        selected.append(pool.pop(best_idx))

    return selected + list(matches[k:]), True


def _dominance_guardrail(
    reliable_matches: list[dict],
    *,
    dominance_ratio: float,
) -> bool:
    if len(reliable_matches) < 2:
        return True
    top_by_doc: dict[int, float] = {}
    for item in reliable_matches:
        dk = _doc_key(item)
        top_by_doc[dk] = max(top_by_doc.get(dk, 0.0), float(item["score"]))
    if len(top_by_doc) < 2:
        return True
    vals = sorted(top_by_doc.values(), reverse=True)
    return vals[0] >= vals[1] * max(1.0, dominance_ratio)


def _select_doc_aware_matches(
    reliable_matches: list[dict],
    *,
    max_chunks_per_doc: int,
    target_distinct_docs: int,
    top_k: int,
    allow_single_doc_dominance: bool,
) -> list[dict]:
    if not reliable_matches:
        return []
    if allow_single_doc_dominance:
        return reliable_matches[:top_k]

    max_per_doc = max(1, max_chunks_per_doc)
    target_docs = max(1, target_distinct_docs)
    selected: list[dict] = []
    selected_ids: set[int] = set()
    per_doc_count: dict[int, int] = defaultdict(int)

    for item in reliable_matches:
        if len(selected) >= top_k:
            break
        dk = _doc_key(item)
        if per_doc_count[dk] > 0:
            continue
        selected.append(item)
        selected_ids.add(item["chunk"].id)
        per_doc_count[dk] += 1
        if len(per_doc_count) >= target_docs:
            break

    for item in reliable_matches:
        if len(selected) >= top_k:
            break
        cid = item["chunk"].id
        if cid in selected_ids:
            continue
        dk = _doc_key(item)
        if per_doc_count[dk] >= max_per_doc:
            continue
        selected.append(item)
        selected_ids.add(cid)
        per_doc_count[dk] += 1
    return selected


def _recover_parent_context_for_packing(
    db: Session,
    items: list[dict],
) -> tuple[list[dict], int]:
    """Merge siblings under same parent for packing; batch-load parents; set _pack_text / _used_parent_for_pack.

    Returns (items_for_packer, parent_deduped_groups). References still use child chunk from each kept item.
    """
    if not items:
        return [], 0
    winners: dict[tuple[str, int], dict] = {}
    for item in items:
        ch = item["chunk"]
        pid = getattr(ch, "parent_chunk_id", None)
        key: tuple[str, int] = ("p", int(pid)) if pid is not None else ("c", int(ch.id))
        if key not in winners or item["score"] > winners[key]["score"]:
            winners[key] = item
    seen: set[tuple[str, int]] = set()
    out: list[dict] = []
    for item in items:
        ch = item["chunk"]
        pid = getattr(ch, "parent_chunk_id", None)
        key = ("p", int(pid)) if pid is not None else ("c", int(ch.id))
        win = winners[key]
        if win is not item:
            continue
        if key in seen:
            continue
        seen.add(key)
        out.append(win)
    parent_deduped_groups = len(out)
    parent_ids = {getattr(it["chunk"], "parent_chunk_id", None) for it in out}
    parent_ids.discard(None)
    parents: dict[int, KnowledgeChunk] = {}
    if parent_ids:
        for row in db.query(KnowledgeChunk).filter(KnowledgeChunk.id.in_(parent_ids)).all():
            parents[row.id] = row
    for it in out:
        ch = it["chunk"]
        pid = getattr(ch, "parent_chunk_id", None)
        use_parent = False
        body = ch.content or ""
        if pid is not None:
            par = parents.get(int(pid))
            if par is not None and (par.content or "").strip():
                body = par.content
                use_parent = True
        it["_pack_text"] = body
        it["_pack_text_primary"] = body
        it["_used_parent_for_pack"] = use_parent
    return out, parent_deduped_groups


def _chunk_meta_dict(chunk: KnowledgeChunk) -> dict:
    return chunk.metadata_json if isinstance(chunk.metadata_json, dict) else {}


def _heading_path_key(chunk: KnowledgeChunk) -> str:
    meta = _chunk_meta_dict(chunk)
    hp = meta.get("heading_path")
    if hp is None:
        return ""
    return str(hp).strip()


def _pack_item_rel_score(item: dict) -> float:
    return float(item.get("rerank_score", item.get("score", 0.0)))


def _pack_primary_text(item: dict) -> str:
    t = item.get("_pack_text_primary")
    if t is not None and str(t).strip():
        return str(t).strip()
    pt = item.get("_pack_text")
    if pt is not None and str(pt).strip():
        return str(pt).strip()
    return (item["chunk"].content or "").strip()


def _mmr_order_pack_items(items: list[dict], *, enabled: bool, mmr_lambda: float) -> list[dict]:
    """对即将参与 packing 的条目做 MMR 重排（基于 primary 正文 Jaccard + 同文档惩罚）。"""
    if not enabled or len(items) <= 1:
        return list(items)
    lam = max(0.0, min(1.0, float(mmr_lambda)))
    pool = list(items)
    selected: list[dict] = []
    while pool:
        if not selected:
            best_idx = 0
        else:
            best_idx = 0
            best_score = -10**9
            for idx, item in enumerate(pool):
                rel = _pack_item_rel_score(item)
                penalties = []
                for chosen in selected:
                    same_doc = 1.0 if _doc_key(chosen) == _doc_key(item) else 0.0
                    sim = _text_jaccard_similarity(_pack_primary_text(chosen), _pack_primary_text(item))
                    penalties.append(max(same_doc * 0.35, sim))
                penalty = max(penalties) if penalties else 0.0
                mmr_score = lam * rel - (1.0 - lam) * penalty
                if mmr_score > best_score:
                    best_score = mmr_score
                    best_idx = idx
        selected.append(pool.pop(best_idx))
    return selected


def _apply_pack_item_diversification(items: list[dict]) -> tuple[list[dict], dict[str, Any]]:
    """在 parent 回收后：MMR 重排 + 文档/heading 配额 + 二阶段补满（避免高分单文档被硬截断）。"""
    if not items:
        return [], {"enabled": False, "input_count": 0, "output_count": 0}

    max_total = max(1, int(app_settings.qa_max_parents_total))
    max_pf = max(1, int(app_settings.qa_max_parents_per_file))
    max_ph = max(1, int(app_settings.qa_max_parents_per_heading))
    same_h = bool(app_settings.qa_same_heading_dedup)
    mmr_on = bool(app_settings.qa_enable_mmr_like_rerank)
    div_on = bool(app_settings.qa_enable_diversification)
    mmr_lambda = float(app_settings.qa_mmr_lambda)

    stats: dict[str, Any] = {
        "enabled": div_on,
        "mmr_applied": mmr_on and div_on,
        "input_count": len(items),
        "max_parents_total": max_total,
        "max_parents_per_file": max_pf,
        "max_parents_per_heading": max_ph,
    }

    if not div_on:
        stats["output_count"] = len(items)
        stats["phase"] = "disabled_pass_through"
        return list(items), stats

    ordered = _mmr_order_pack_items(items, enabled=mmr_on, mmr_lambda=mmr_lambda)
    phase1: list[dict] = []
    per_file: dict[int, int] = defaultdict(int)
    per_head: dict[tuple[int, str], int] = defaultdict(int)
    seen_id: set[int] = set()

    for it in ordered:
        ch = it["chunk"]
        cid = int(ch.id)
        if cid in seen_id:
            continue
        fid = int(ch.file_id)
        hk = (fid, _heading_path_key(ch))
        if per_file[fid] >= max_pf:
            continue
        if same_h and per_head[hk] >= max_ph:
            continue
        phase1.append(it)
        seen_id.add(cid)
        per_file[fid] += 1
        per_head[hk] += 1
        if len(phase1) >= max_total:
            break

    after_quota_pass = len(phase1)

    # 二阶段：按原始相关性补满槽位（可突破 per_file / heading 限额，但仍受 max_total 约束）
    for it in sorted(ordered, key=_pack_item_rel_score, reverse=True):
        if len(phase1) >= max_total:
            break
        cid = int(it["chunk"].id)
        if cid in seen_id:
            continue
        phase1.append(it)
        seen_id.add(cid)

    stats["output_count"] = len(phase1)
    stats["after_quota_pass_count"] = after_quota_pass
    stats["distinct_files_after"] = len({int(x["chunk"].file_id) for x in phase1})
    return phase1, stats


def _prepare_pack_items_with_diversification(
    pack_items: list[dict],
    *,
    selected_reliable_matches: list[dict],
    deduped_expanded_count: int,
    query_type: str = "factual",
) -> tuple[list[dict], dict[str, Any] | None]:
    """parent 回收并相邻扩展之后：coverage-aware 两阶段选择或旧多样化；trace 供 retrieval_meta。"""
    n_before = len(pack_items)
    seed_ids = {int(x["chunk"].id) for x in selected_reliable_matches}
    coverage_selection_trace: dict[str, Any] | None = None
    if bool(app_settings.qa_enable_coverage_aware_packing):
        max_total = max(1, int(app_settings.qa_max_parents_total))
        diversified, cov_trace = select_pack_items_coverage_two_phase(
            pack_items,
            query_type=str(query_type or "factual"),
            seed_chunk_ids=seed_ids,
            max_total=max_total,
        )
        coverage_selection_trace = dict(cov_trace)
        div_stats: dict[str, Any] = {
            "enabled": True,
            "mode": "coverage_aware",
            "pack_items_before_diversify": n_before,
            **cov_trace,
        }
    else:
        diversified, div_stats = _apply_pack_item_diversification(pack_items)
        div_stats["pack_items_before_diversify"] = n_before
        div_stats.setdefault("mode", "legacy_diversification")
    trace: dict[str, Any] | None = None
    if bool(app_settings.qa_debug_retrieval_trace_enabled) or bool(app_settings.qa_enable_coverage_diagnostics):
        trace = {"pack_diversification": dict(div_stats)}
        if coverage_selection_trace is not None:
            trace["coverage_selection"] = coverage_selection_trace
        if bool(app_settings.qa_debug_store_intermediate_matches):
            trace["selected_child_chunk_ids"] = [int(x["chunk"].id) for x in selected_reliable_matches]
            trace["deduped_expanded_item_count"] = int(deduped_expanded_count)
    return diversified, trace


def _expand_adjacent_parent_context(db: Session, items: list[dict]) -> None:
    """在已回收 parent 正文的基础上，按配置拼接同文件相邻 parent，补全跨段语义（有总字数上限）。"""
    n_side = max(0, int(app_settings.qa_adjacent_parent_max_per_side))
    max_extra = max(0, int(app_settings.qa_adjacent_parent_max_chars))
    same_heading_only = bool(app_settings.qa_adjacent_parent_same_heading_only)
    if n_side <= 0 or max_extra <= 0 or not items:
        for it in items:
            it.setdefault("_adjacent_parent_chunks", [])
            it.setdefault("_context_adjacent_expanded", False)
        return

    parents_by_file: dict[int, list[KnowledgeChunk]] = {}
    file_ids = {int(it["chunk"].file_id) for it in items}
    for fid in file_ids:
        rows = (
            db.query(KnowledgeChunk)
            .filter(
                KnowledgeChunk.file_id == fid,
                KnowledgeChunk.chunk_kind == "parent",
            )
            .order_by(KnowledgeChunk.chunk_index.asc())
            .all()
        )
        parents_by_file[fid] = rows

    for it in items:
        it.setdefault("_adjacent_parent_chunks", [])
        it.setdefault("_context_adjacent_expanded", False)
        if not it.get("_used_parent_for_pack"):
            continue
        ch = it["chunk"]
        pid = getattr(ch, "parent_chunk_id", None)
        if pid is None:
            continue
        par = db.query(KnowledgeChunk).filter(KnowledgeChunk.id == int(pid)).first()
        if par is None:
            continue
        base_hp = _heading_path_key(par)
        plist = parents_by_file.get(int(par.file_id), [])
        if not plist:
            continue
        idx = next((i for i, p in enumerate(plist) if p.id == par.id), None)
        if idx is None:
            continue
        extras: list[str] = []
        adj_meta: list[dict[str, Any]] = []
        used = 0
        for off in range(1, n_side + 1):
            for ni in (idx - off, idx + off):
                if ni < 0 or ni >= len(plist):
                    continue
                nb = plist[ni]
                body = (nb.content or "").strip()
                if not body or nb.id == par.id:
                    continue
                if same_heading_only:
                    nh = _heading_path_key(nb)
                    if base_hp != nh:
                        continue
                sep_cost = 12
                if used + len(body) + sep_cost > max_extra:
                    continue
                extras.append(body)
                adj_meta.append(
                    {
                        "chunk_id": int(nb.id),
                        "heading_path": _heading_path_key(nb) or None,
                    }
                )
                used += len(body) + sep_cost
        if not extras:
            continue
        base = (it.get("_pack_text") or "").strip()
        it["_pack_text"] = base + "\n\n---\n【相邻 parent 扩展】\n" + "\n\n".join(extras)
        it["_context_adjacent_expanded"] = True
        it["_adjacent_parent_chunks"] = adj_meta


def _pack_context_and_references(
    items: list[dict],
    *,
    seed_chunk_ids: set[int],
    max_context_chars: int,
    dedupe_adjacent_chunks: bool,
    redundancy_sim_threshold: float,
    redundancy_adjacent_window: int,
    packing_trace: dict[str, Any] | None = None,
    query_type: str = "factual",
    retrieval_queries: list[str] | None = None,
) -> tuple[list[str], list[dict], list[int], int, int, int, float]:
    """
    Greedy pack into max_context_chars. Prioritize seed hits（再按相关性、文件、序号）。
    使用 _pack_text 作为 LLM 块正文；引用仍指向检索命中的 child。
    """
    if max_context_chars < 1:
        return [], [], [], 0, 0, 0, 0.0

    parent_sim_thr = max(0.0, min(1.0, float(app_settings.qa_parent_similarity_dedup_threshold)))
    budget_ratio = max(0.2, min(1.0, float(app_settings.qa_pack_per_file_budget_ratio)))
    distinct_files = len({int(it["chunk"].file_id) for it in items}) if items else 1
    ratio_cap = max_context_chars if distinct_files <= 1 else int(max_context_chars * budget_ratio)
    abs_cap = int(app_settings.qa_max_context_chars_per_file)
    if distinct_files > 1 and abs_cap > 0:
        per_file_cap = min(ratio_cap, abs_cap)
    else:
        per_file_cap = ratio_cap

    def sort_key(it: dict) -> tuple:
        cid = it["chunk"].id
        is_seed = 1 if cid in seed_chunk_ids else 0
        return (-is_seed, -_pack_item_rel_score(it), it["chunk"].file_id, it["chunk"].chunk_index)

    sorted_items = sorted(items, key=sort_key)
    context_blocks: list[str] = []
    references: list[dict] = []
    used_files: list[int] = []
    total_chars = 0
    last_content_norm: str | None = None
    parent_recovered_chunks = 0
    suppressed_redundant = 0
    suppressed_parent_sim = 0
    suppressed_file_budget = 0
    considered = 0
    by_doc_kept: dict[int, list[tuple[int, str]]] = defaultdict(list)
    packed_primary_norms: list[str] = []
    doc_char_totals: dict[int, int] = defaultdict(int)

    for item in sorted_items:
        considered += 1
        chunk = item["chunk"]
        body = item.get("_pack_text")
        if body is None:
            body = chunk.content
        body = body or ""
        meta = _chunk_meta_dict(chunk)
        hp = meta.get("heading_path")
        hp_s = str(hp).strip() if hp is not None else ""
        psi = meta.get("parent_sequence_index")
        blk = meta.get("block_type")
        pid = getattr(chunk, "parent_chunk_id", None)
        sep = "\n\n" if context_blocks else ""
        header = (
            f"[文件: {item['file_name']} | heading_path: {hp_s or '—'} "
            f"| parent_seq: {psi if psi is not None else '—'} | block: {blk or '—'} "
            f"| hit_child_chunk: {chunk.chunk_index}]"
        )
        block = f"{header}\n{body}"
        add_len = len(sep) + len(block)
        fid = int(chunk.file_id)
        if total_chars + add_len > max_context_chars:
            break
        if distinct_files > 1 and doc_char_totals[fid] + add_len > per_file_cap:
            suppressed_file_budget += 1
            continue

        primary_norm = _pack_primary_text(item)
        content_norm = body.strip()
        if dedupe_adjacent_chunks and last_content_norm is not None and content_norm == last_content_norm:
            suppressed_redundant += 1
            continue

        dup_sim = False
        for prev in packed_primary_norms:
            if _text_jaccard_similarity(primary_norm, prev) >= parent_sim_thr:
                dup_sim = True
                break
        if dup_sim:
            suppressed_parent_sim += 1
            continue

        if dedupe_adjacent_chunks:
            same_doc = by_doc_kept.get(fid, [])
            suppressed = False
            for kept_index, kept_body in same_doc:
                if abs(int(chunk.chunk_index) - kept_index) > max(0, redundancy_adjacent_window):
                    continue
                sim = _text_jaccard_similarity(content_norm, kept_body)
                if sim >= max(0.0, min(1.0, redundancy_sim_threshold)):
                    suppressed = True
                    break
            if suppressed:
                suppressed_redundant += 1
                continue

        context_blocks.append(block)
        if item.get("_used_parent_for_pack"):
            parent_recovered_chunks += 1
        packed_primary_norms.append(primary_norm)

        adj_exp = bool(item.get("_context_adjacent_expanded"))
        adj_ids = [int(x["chunk_id"]) for x in (item.get("_adjacent_parent_chunks") or []) if x.get("chunk_id") is not None]
        prov_type, prov_tags, ctx_role = resolve_pack_provenance(item, seed_chunk_ids)
        qi = int(item.get("matched_query_index", -1))
        rq = retrieval_queries or []
        mq = rq[qi] if 0 <= qi < len(rq) else None

        ref: dict[str, Any] = {
            "file_id": chunk.file_id,
            "file_name": item["file_name"],
            "chunk_id": chunk.id,
            "chunk_index": chunk.chunk_index,
            "snippet": _build_snippet(chunk.content),
            "score": float(item["score"]),
            "section_title": chunk.section_title,
            "page_number": chunk.page_number,
            "heading_path": meta.get("heading_path"),
            "block_type": meta.get("block_type"),
            "chunk_role": meta.get("chunk_role"),
            "ref_origin": "retrieval_child_hit",
            "context_chunk_role": ctx_role,
            "parent_chunk_id": int(pid) if pid is not None else None,
            "parent_sequence_index": psi,
            "adjacent_expansion": adj_exp,
            "adjacent_parent_chunk_ids": adj_ids,
        }
        if bool(app_settings.qa_enable_citation_provenance):
            ref["provenance_type"] = prov_type
            ref["provenance_tags"] = prov_tags
            ref["source_reason"] = str(item.get("source_reason") or "retrieval_hit")
            ref["matched_query_index"] = qi
            ref["matched_query"] = mq
            ref["query_type"] = str(query_type)
            ref["rerank_score"] = float(item.get("rerank_score", item.get("score", 0.0)))
        references.append(ref)
        if chunk.file_id not in used_files:
            used_files.append(chunk.file_id)
        total_chars += add_len
        doc_char_totals[fid] += add_len
        last_content_norm = content_norm
        by_doc_kept[fid].append((int(chunk.chunk_index), content_norm))

    redundancy_rate = suppressed_redundant / considered if considered else 0.0
    total_ctx_chars = sum(doc_char_totals.values())
    file_rank_order = rank_files_by_context_chars(dict(doc_char_totals))
    rank_by_fid = {fid: idx + 1 for idx, fid in enumerate(file_rank_order)}
    for ref in references:
        try:
            rf = int(ref.get("file_id", 0))
        except (TypeError, ValueError):
            continue
        if bool(app_settings.qa_enable_citation_provenance):
            ref["source_file_rank"] = rank_by_fid.get(rf)
            ref["file_char_share"] = (
                round(doc_char_totals[rf] / total_ctx_chars, 4) if total_ctx_chars and rf in doc_char_totals else 0.0
            )
    if packing_trace is not None:
        packing_trace.update(
            {
                "considered_items": considered,
                "packed_blocks": len(context_blocks),
                "suppressed_redundant_adjacent": suppressed_redundant,
                "suppressed_parent_similarity": suppressed_parent_sim,
                "suppressed_file_budget": suppressed_file_budget,
                "per_file_context_chars": {str(k): v for k, v in doc_char_totals.items()},
                "per_file_cap": per_file_cap,
                "per_file_cap_ratio_basis": ratio_cap,
                "per_file_cap_absolute": abs_cap if distinct_files > 1 else None,
                "distinct_files_in_input": distinct_files,
                "parent_similarity_threshold": parent_sim_thr,
            }
        )
    return context_blocks, references, used_files, total_chars, len(references), parent_recovered_chunks, redundancy_rate


def _assemble_evidence_bundles(references: list[dict]) -> dict:
    by_file: dict[int, dict] = {}
    for ref in references:
        if not isinstance(ref, dict):
            continue
        file_id = int(ref.get("file_id", 0))
        if file_id <= 0:
            continue
        bucket = by_file.setdefault(
            file_id,
            {
                "file_id": file_id,
                "file_name": ref.get("file_name"),
                "max_score": 0.0,
                "citations": [],
            },
        )
        score = float(ref.get("score") or 0.0)
        bucket["max_score"] = max(bucket["max_score"], score)
        bucket["citations"].append(
            {
                "chunk_id": ref.get("chunk_id"),
                "chunk_index": ref.get("chunk_index"),
                "section_title": ref.get("section_title"),
                "page_number": ref.get("page_number"),
                "score": score,
            }
        )

    ranked = sorted(by_file.values(), key=lambda item: item["max_score"], reverse=True)
    primary = ranked[:2]
    supplemental = ranked[2:]
    return {
        "primary_sources": primary,
        "supplementary_sources": supplemental,
        "source_count": len(ranked),
    }


def _compare_side_coverage_hint(compare_targets: list[str], references: list[dict]) -> dict[str, Any]:
    """低成本 compare 侧覆盖信号：用于 diagnostics（非严谨 NER）。"""
    if len(compare_targets) < 2:
        return {"sides_covered_approx": 0, "note": "need_two_targets"}
    a, b = (compare_targets[0] or "").lower(), (compare_targets[1] or "").lower()
    if not a or not b:
        return {"sides_covered_approx": 0, "note": "empty_target"}
    has_a = has_b = False
    for ref in references:
        if not isinstance(ref, dict):
            continue
        blob = " ".join(
            str(ref.get(k) or "") for k in ("file_name", "snippet", "section_title", "heading_path")
        ).lower()
        if a in blob:
            has_a = True
        if b in blob:
            has_b = True
    return {
        "side_a_signal": has_a,
        "side_b_signal": has_b,
        "sides_covered_approx": int(has_a) + int(has_b),
    }


def _compute_source_coverage_metrics(references: list[dict], *, top_k: int) -> dict[str, float | int]:
    by_file: dict[int, int] = defaultdict(int)
    for ref in references:
        if not isinstance(ref, dict):
            continue
        try:
            file_id = int(ref.get("file_id"))
        except (TypeError, ValueError):
            continue
        by_file[file_id] += 1
    total_refs = sum(by_file.values())
    source_count = len(by_file)
    dominant_source_ratio = (max(by_file.values()) / total_refs) if total_refs else 0.0
    coverage_denominator = max(1, min(top_k, 3))
    multi_source_coverage = min(1.0, source_count / coverage_denominator)
    return {
        "source_count": source_count,
        "dominant_source_ratio": round(dominant_source_ratio, 4),
        "multi_source_coverage": round(multi_source_coverage, 4),
        "source_distribution": {str(k): v for k, v in by_file.items()},
        "coverage_denominator": coverage_denominator,
    }


def _build_compare_result(compare_targets: list[str], references: list[dict]) -> dict[str, Any]:
    target_a = compare_targets[0] if len(compare_targets) >= 1 else "A"
    target_b = compare_targets[1] if len(compare_targets) >= 2 else "B"
    side_a_evidence: list[dict[str, Any]] = []
    side_b_evidence: list[dict[str, Any]] = []
    overflow_targets = compare_targets[2:] if len(compare_targets) > 2 else []
    for ref in references:
        if not isinstance(ref, dict):
            continue
        candidate = {
            "file_id": ref.get("file_id"),
            "file_name": ref.get("file_name"),
            "chunk_id": ref.get("chunk_id"),
            "chunk_index": ref.get("chunk_index"),
            "snippet": ref.get("snippet"),
            "score": ref.get("score"),
        }
        signal = " ".join([str(ref.get("file_name") or ""), str(ref.get("section_title") or ""), str(ref.get("snippet") or "")]).lower()
        match_a = target_a and target_a.lower() in signal
        match_b = target_b and target_b.lower() in signal
        if match_a and not match_b:
            side_a_evidence.append(candidate)
        elif match_b and not match_a:
            side_b_evidence.append(candidate)
        elif match_a and match_b:
            if len(side_a_evidence) <= len(side_b_evidence):
                side_a_evidence.append(candidate)
            else:
                side_b_evidence.append(candidate)
        elif len(side_a_evidence) <= len(side_b_evidence):
            side_a_evidence.append(candidate)
        else:
            side_b_evidence.append(candidate)

    common_points: list[str] = []
    differences: list[str] = []
    conflicts: list[str] = []
    min_side = min(len(side_a_evidence), len(side_b_evidence))
    max_side = max(len(side_a_evidence), len(side_b_evidence), 1)
    symmetry = round(min_side / max_side, 4)
    evidence_sufficiency = bool(side_a_evidence and side_b_evidence)
    asymmetry = symmetry < 0.6
    if evidence_sufficiency:
        common_points.append("两侧均检索到可引用证据。")
    else:
        differences.append("至少一侧证据不足，比较结论仅可作为保守参考。")
    if asymmetry:
        conflicts.append("两侧证据分布明显不对称，存在单侧偏结论风险。")
    if overflow_targets:
        differences.append("检测到超过两个比较对象，本轮仅稳定比较前两侧。")

    compare_confidence = 0.3 + (0.4 if evidence_sufficiency else 0.0) + (0.3 * symmetry)
    return {
        "comparison_targets": compare_targets[:2],
        "overflow_targets": overflow_targets,
        "side_a_label": target_a,
        "side_b_label": target_b,
        "side_a_evidence": side_a_evidence,
        "side_b_evidence": side_b_evidence,
        "common_points": common_points,
        "differences": differences,
        "conflicts": conflicts,
        "evidence_sufficiency": evidence_sufficiency,
        "evidence_symmetry": symmetry,
        "evidence_asymmetry": asymmetry,
        "compare_confidence": round(min(1.0, compare_confidence), 4),
    }


class QAServiceError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _qa_model_runtime_error(stage: str, exc: BaseException) -> QAServiceError:
    """将 RuntimeError 细分为可展示、可日志定位的 QA 错误（不吞掉原始信息）。"""
    detail = str(exc).strip() if exc else ""
    if len(detail) > 1200:
        detail = detail[:1200] + "…"
    low = detail.lower()
    if stage == "embed" or "embedding" in low or "embed" in low[:80]:
        code = "EMBEDDING_REQUEST_FAILED"
        msg = detail or "Embedding 调用失败，请检查 API Key、Base URL、模型名与网络。"
    elif "recursion" in low or isinstance(exc, RecursionError):
        code = "QA_INTERNAL_ERROR"
        msg = detail or "问答内部处理异常，请稍后重试或联系管理员。"
    elif "readtimeout" in low or "超时" in detail or "timeout" in low:
        code = "MODEL_TIMEOUT"
        msg = detail or "模型请求超时，可稍后重试或增大 llm_timeout / embedding_timeout。"
    elif "429" in detail or "rate_limit" in low or "限流" in detail or "quota" in low:
        code = "MODEL_RATE_LIMITED"
        msg = detail or "模型服务限流或配额不足。"
    elif "401" in detail or "403" in detail or "auth" in low or "认证" in detail:
        code = "MODEL_AUTH_FAILED"
        msg = detail or "模型服务认证失败，请检查 API Key。"
    elif "404" in detail or "not found" in low or "不存在" in detail:
        code = "MODEL_NOT_FOUND"
        msg = detail or "模型或接口路径不存在，请检查 model 名与 Base URL（如 OpenAI 兼容需 /v1）。"
    else:
        code = "MODEL_REQUEST_FAILED"
        msg = detail or "模型服务请求失败，请检查当前配置与连接状态。"
    return QAServiceError(code, msg)


def ensure_session(
    db: Session,
    *,
    user_id: int,
    session_id: int | None,
    scope_type: str,
    folder_id: int | None,
) -> QASession:
    if session_id is not None:
        session = (
            db.query(QASession)
            .filter(QASession.id == session_id, QASession.user_id == user_id)
            .first()
        )
        if session:
            session.scope_type = scope_type
            session.folder_id = folder_id
            session.updated_at = datetime.utcnow()
            db.commit()
            db.refresh(session)
            return session

    session = QASession(
        user_id=user_id,
        title=None,
        scope_type=scope_type,
        folder_id=folder_id,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def append_qa_messages(
    db: Session,
    *,
    session_id: int,
    question: str,
    answer: str,
    references_json: list[dict] | dict | None,
) -> tuple[QAMessage, QAMessage]:
    now = datetime.utcnow()
    user_message = QAMessage(
        session_id=session_id,
        role="user",
        content=question,
        references_json=None,
        created_at=now,
    )
    assistant_message = QAMessage(
        session_id=session_id,
        role="assistant",
        content=answer,
        references_json=references_json,
        created_at=now,
    )
    db.add(user_message)
    db.add(assistant_message)
    session = db.query(QASession).filter(QASession.id == session_id).first()
    if session:
        if not session.title:
            session.title = question[:80]
        session.updated_at = now
    db.commit()
    db.refresh(user_message)
    db.refresh(assistant_message)
    return user_message, assistant_message


def append_qa_failure(
    db: Session,
    *,
    session_id: int,
    question: str,
    error_message: str,
    error_code: str | None = None,
) -> tuple[QAMessage, QAMessage]:
    now = datetime.utcnow()
    user_message = QAMessage(
        session_id=session_id,
        role="user",
        content=question,
        references_json=None,
        created_at=now,
    )
    assistant_message = QAMessage(
        session_id=session_id,
        role="assistant",
        content=error_message,
        references_json={"kind": "error", "code": error_code} if error_code else {"kind": "error"},
        created_at=now,
    )
    db.add(user_message)
    db.add(assistant_message)
    session = db.query(QASession).filter(QASession.id == session_id).first()
    if session:
        if not session.title:
            session.title = question[:80]
        session.updated_at = now
    db.commit()
    db.refresh(user_message)
    db.refresh(assistant_message)
    return user_message, assistant_message


def list_session_messages(
    db: Session,
    *,
    session_id: int,
    user_id: int,
) -> list[dict]:
    session = (
        db.query(QASession)
        .filter(QASession.id == session_id, QASession.user_id == user_id)
        .first()
    )
    if not session:
        raise QAServiceError("SESSION_NOT_FOUND", "问答会话不存在")

    rows = (
        db.query(QAMessage)
        .filter(QAMessage.session_id == session_id)
        .order_by(QAMessage.created_at.asc(), QAMessage.id.asc())
        .all()
    )
    return [
        {
            "id": row.id,
            "session_id": row.session_id,
            "role": row.role,
            "content": row.content,
            "references_json": row.references_json,
            "state": (
                "error"
                if row.role == "assistant"
                and isinstance(row.references_json, dict)
                and row.references_json.get("kind") == "error"
                else "normal"
            ),
            "created_at": row.created_at.isoformat(),
        }
        for row in rows
    ]


def list_user_sessions(
    db: Session,
    *,
    user_id: int,
) -> list[dict]:
    sessions = (
        db.query(QASession)
        .filter(QASession.user_id == user_id)
        .order_by(QASession.updated_at.desc(), QASession.id.desc())
        .all()
    )
    items: list[dict] = []
    for session in sessions:
        last_user_message = (
            db.query(QAMessage)
            .filter(QAMessage.session_id == session.id, QAMessage.role == "user")
            .order_by(QAMessage.created_at.desc(), QAMessage.id.desc())
            .first()
        )
        last_assistant_message = (
            db.query(QAMessage)
            .filter(QAMessage.session_id == session.id, QAMessage.role == "assistant")
            .order_by(QAMessage.created_at.desc(), QAMessage.id.desc())
            .first()
        )
        message_count = (
            db.query(QAMessage).filter(QAMessage.session_id == session.id).count()
        )
        last_error = None
        if last_assistant_message and isinstance(last_assistant_message.references_json, dict):
            if last_assistant_message.references_json.get("kind") == "error":
                last_error = last_assistant_message.content
        items.append(
            {
                "id": session.id,
                "title": session.title or (last_user_message.content[:80] if last_user_message else "新会话"),
                "scope_type": session.scope_type,
                "folder_id": session.folder_id,
                "last_question": last_user_message.content if last_user_message else None,
                "last_error": last_error,
                "message_count": message_count,
                "updated_at": session.updated_at.isoformat(),
                "created_at": session.created_at.isoformat(),
            }
        )
    return items


def delete_session(
    db: Session,
    *,
    session_id: int,
    user_id: int,
) -> None:
    session = (
        db.query(QASession)
        .filter(QASession.id == session_id, QASession.user_id == user_id)
        .first()
    )
    if not session:
        raise QAServiceError("SESSION_NOT_FOUND", "问答会话不存在")
    db.delete(session)
    db.commit()


def _build_snippet(text: str, limit: int = SNIPPET_TRUNCATE_LENGTH) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[:limit].rstrip()}..."


def _cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _get_descendant_ids(db: Session, folder_id: int) -> set[int]:
    descendant_ids: set[int] = set()
    queue: list[int] = [folder_id]
    while queue:
        current_id = queue.pop()
        children = db.query(Folder).filter(Folder.parent_id == current_id).all()
        for child in children:
            if child.id in descendant_ids:
                continue
            descendant_ids.add(child.id)
            queue.append(child.id)
    return descendant_ids


def _load_settings(db: Session) -> SystemSetting:
    settings = db.query(SystemSetting).filter(SystemSetting.id == 1).first()
    if not settings:
        raise QAServiceError("SETTINGS_NOT_FOUND", "系统设置不存在")
    return settings


def _list_files_in_scope(
    db: Session,
    *,
    scope_type: str,
    folder_id: int | None,
    file_ids: list[int] | None,
) -> list[FileRecord]:
    query = db.query(FileRecord)
    if scope_type == "folder" and folder_id is not None:
        scope_folder_ids = {folder_id, *_get_descendant_ids(db, folder_id)}
        query = query.filter(FileRecord.folder_id.in_(scope_folder_ids))
    elif scope_type == "files":
        if not file_ids:
            return []
        query = query.filter(FileRecord.id.in_(file_ids))
    return query.order_by(FileRecord.id.asc()).all()


def _collect_retrievable_file_ids(
    db: Session,
    *,
    settings: SystemSetting,
    scope_type: str,
    folder_id: int | None,
    file_ids: list[int] | None,
    expected_dimension: int | None,
    current_user: User | None = None,
) -> list[int]:
    current_standard = build_embedding_index_standard(
        embedding_provider=settings.embedding_provider,
        embedding_model=settings.embedding_model,
    )
    if not current_standard:
        return []

    scoped_files = _list_files_in_scope(
        db,
        scope_type=scope_type,
        folder_id=folder_id,
        file_ids=file_ids,
    )
    if current_user is not None:
        from app.core.permissions import user_may_access_file_record

        scoped_files = [
            f for f in scoped_files if user_may_access_file_record(db, current_user, f)
        ]
    compatible_indexed_file_ids: list[int] = []
    for file_record in scoped_files:
        if file_record.index_status != "indexed":
            continue
        file_standard = build_embedding_index_standard(
            embedding_provider=file_record.index_embedding_provider,
            embedding_model=file_record.index_embedding_model,
        )
        if file_standard != current_standard:
            continue
        if expected_dimension is not None and file_record.index_embedding_dimension != expected_dimension:
            continue
        compatible_indexed_file_ids.append(file_record.id)

    if not compatible_indexed_file_ids:
        return []

    retrievable_ids = (
        db.query(KnowledgeChunk.file_id)
        .filter(KnowledgeChunk.file_id.in_(compatible_indexed_file_ids))
        .filter(_child_or_legacy_retrieval_filter())
        .filter(KnowledgeChunk.embedding.is_not(None))
        .filter(KnowledgeChunk.token_count.is_not(None))
        .filter(KnowledgeChunk.token_count >= MIN_RETRIEVAL_CHUNK_CHARS)
        .distinct()
        .all()
    )
    return [file_id for (file_id,) in retrievable_ids]


def _retrieve_chunks(
    db: Session,
    *,
    query_embedding: list[float],
    compatible_file_ids: list[int],
    top_k: int,
) -> list[dict]:
    top_k = max(MIN_TOP_K, min(top_k, MAX_TOP_K))
    expected_dimension = len(query_embedding)
    if expected_dimension == 0:
        raise QAServiceError("EMBEDDING_DATA_UNAVAILABLE", "查询向量为空，无法执行检索")
    if not compatible_file_ids:
        return []

    query = (
        db.query(KnowledgeChunk, FileRecord.file_name, FileRecord.folder_id)
        .join(FileRecord, KnowledgeChunk.file_id == FileRecord.id)
        .filter(KnowledgeChunk.file_id.in_(compatible_file_ids))
        .filter(_child_or_legacy_retrieval_filter())
        .filter(KnowledgeChunk.embedding.is_not(None))
        .filter(KnowledgeChunk.token_count.is_not(None))
        .filter(KnowledgeChunk.token_count >= MIN_RETRIEVAL_CHUNK_CHARS)
    )

    candidates = query.all()
    ranked: list[dict] = []
    for chunk, file_name, chunk_folder_id in candidates:
        embedding = chunk.embedding or []
        if not embedding:
            continue
        if len(embedding) != expected_dimension:
            raise QAServiceError(
                "EMBEDDING_DIMENSION_MISMATCH",
                "当前索引数据的 embedding 维度不一致，请重新索引相关文件",
            )
        if not chunk.content.strip() or (chunk.token_count or 0) < MIN_RETRIEVAL_CHUNK_CHARS:
            continue
        score = _cosine_similarity(query_embedding, embedding)
        ranked.append(
            {
                "chunk": chunk,
                "file_name": file_name,
                "folder_id": chunk_folder_id,
                "score": score,
            }
        )

    ranked.sort(key=lambda item: item["score"], reverse=True)
    return ranked[:top_k]


def _semantic_retrieval_app_layer(
    db: Session,
    *,
    query_embedding: list[float],
    compatible_file_ids: list[int],
    top_k: int,
) -> list[dict]:
    """Semantic (vector) retrieval; delegates to existing _retrieve_chunks."""
    return _retrieve_chunks(
        db,
        query_embedding=query_embedding,
        compatible_file_ids=compatible_file_ids,
        top_k=top_k,
    )


def _semantic_retrieval_pgvector(
    db: Session,
    *,
    query_embedding: list[float],
    compatible_file_ids: list[int],
    top_k: int,
) -> list[dict]:
    if not compatible_file_ids or not query_embedding:
        return []
    # knowledge_chunks.embedding_vec 为固定维度（见迁移 vector(1024)，须与智谱请求 dimensions 及 qa_pgvector_dimensions 一致）；查询向量维度不一致时
    # 不能绑定到 <=>，否则 SQLAlchemy/pgvector 抛 StatementError。此时走上层 app-layer 余弦。
    if len(query_embedding) != app_settings.qa_pgvector_dimensions:
        logger.info(
            "pgvector query skipped: embedding_dim=%s expected=%s (use ARRAY embedding fallback)",
            len(query_embedding),
            app_settings.qa_pgvector_dimensions,
        )
        return []
    try:
        distance_expr = KnowledgeChunk.embedding_vec.cosine_distance(query_embedding)
        rows = (
            db.query(KnowledgeChunk, FileRecord.file_name, FileRecord.folder_id, distance_expr.label("distance"))
            .join(FileRecord, KnowledgeChunk.file_id == FileRecord.id)
            .filter(KnowledgeChunk.file_id.in_(compatible_file_ids))
            .filter(_child_or_legacy_retrieval_filter())
            .filter(KnowledgeChunk.embedding_vec.is_not(None))
            .order_by(distance_expr.asc())
            .limit(top_k)
            .all()
        )
    except Exception:
        logger.exception("pgvector semantic retrieval failed; fallback to app-layer cosine")
        raise

    ranked: list[dict] = []
    for chunk, file_name, folder_id, distance in rows:
        dist = float(distance) if distance is not None else 1.0
        score = max(0.0, 1.0 - dist)
        ranked.append(
            {
                "chunk": chunk,
                "file_name": file_name,
                "folder_id": folder_id,
                "score": score,
                "source": "semantic",
            }
        )
    ranked.sort(key=lambda it: it["score"], reverse=True)
    return ranked[:top_k]


def _semantic_retrieval(
    db: Session,
    *,
    query_embeddings: list[list[float]],
    compatible_file_ids: list[int],
    top_k: int,
) -> tuple[list[dict], str]:
    if not query_embeddings:
        return [], DEFAULT_RETRIEVAL_STRATEGY

    # Primary path: pgvector ANN
    if app_settings.qa_pgvector_retrieval_enabled and app_settings.qa_pgvector_semantic_enabled:
        all_candidates: dict[int, dict] = {}
        try:
            probe_limit = max(top_k, int(app_settings.qa_pgvector_probe_limit))
            for qi, query_embedding in enumerate(query_embeddings):
                for item in _semantic_retrieval_pgvector(
                    db,
                    query_embedding=query_embedding,
                    compatible_file_ids=compatible_file_ids,
                    top_k=probe_limit,
                ):
                    cid = item["chunk"].id
                    tagged = {**item, "matched_query_index": qi, "source": "semantic"}
                    if cid not in all_candidates or item["score"] > all_candidates[cid]["score"]:
                        all_candidates[cid] = tagged
            merged = list(all_candidates.values())
            merged.sort(key=lambda it: it["score"], reverse=True)
            if merged:
                return merged[:top_k], "pgvector_ann_hnsw"
        except Exception:
            logger.info("pgvector unavailable; switching to app-layer cosine fallback")

    # Fallback: app-layer cosine scan
    all_candidates: dict[int, dict] = {}
    for qi, query_embedding in enumerate(query_embeddings):
        for item in _semantic_retrieval_app_layer(
            db,
            query_embedding=query_embedding,
            compatible_file_ids=compatible_file_ids,
            top_k=max(top_k, int(app_settings.qa_pgvector_probe_limit)),
        ):
            cid = item["chunk"].id
            tagged = {**item, "source": "semantic", "matched_query_index": qi}
            if cid not in all_candidates or item["score"] > all_candidates[cid]["score"]:
                all_candidates[cid] = tagged
    merged = list(all_candidates.values())
    merged.sort(key=lambda it: it["score"], reverse=True)
    return merged[:top_k], DEFAULT_RETRIEVAL_STRATEGY


def _lexical_retrieval(
    db: Session,
    *,
    questions: list[str],
    compatible_file_ids: list[int],
    top_k: int,
) -> list[dict]:
    """Lexical retrieval via PostgreSQL FTS.

    Priority:
    1. KnowledgeChunk.search_vector @@ websearch_to_tsquery (uses GIN index)
    2. Fallback: inline to_tsvector(content) @@ websearch_to_tsquery
    """
    if not compatible_file_ids or not questions:
        return []

    def _do_query(tsvector_expr, q: str) -> list[dict]:
        query = (
            db.query(KnowledgeChunk, FileRecord.file_name, FileRecord.folder_id)
            .join(FileRecord, KnowledgeChunk.file_id == FileRecord.id)
            .filter(KnowledgeChunk.file_id.in_(compatible_file_ids))
            .filter(_child_or_legacy_retrieval_filter())
            .filter(
                tsvector_expr.op("@@")(
                    func.websearch_to_tsquery("simple", q)
                )
            )
            .order_by(KnowledgeChunk.id.asc())
            .limit(top_k)
        )

        ranked: list[dict] = []
        for chunk, file_name, folder_id in query.all():
            ranked.append(
                {
                    "chunk": chunk,
                    "file_name": file_name,
                    "folder_id": folder_id,
                    # Lightweight lexical score; NOT comparable to semantic cosine.
                    # RRF fusion normalizes by rank, so absolute value doesn't matter.
                    "score": 1.0,
                    "source": "lexical",
                }
            )
        return ranked

    merged: dict[int, dict] = {}
    for qi, q in enumerate(questions):
        if not q.strip():
            continue
        # 1) Prefer search_vector (indexed GIN column)
        try:
            result = _do_query(KnowledgeChunk.search_vector, q)
        except Exception:
            result = []
        # 2) Fallback: inline to_tsvector(content)
        if not result:
            try:
                result = _do_query(
                    func.to_tsvector(
                        "simple",
                        func.coalesce(KnowledgeChunk.content, ""),
                    ),
                    q,
                )
            except Exception:
                result = []
        for item in result:
            cid = item["chunk"].id
            tagged = {**item, "matched_query_index": qi}
            if cid not in merged:
                merged[cid] = tagged
    out = list(merged.values())
    out.sort(key=lambda it: (it["chunk"].file_id, it["chunk"].chunk_index))
    return out[:top_k]


_RRF_K = 60


def _dedup_key(item: dict) -> int:
    """Primary dedup by chunk.id; fallback to (file_id, chunk_index) composite."""
    chunk = item["chunk"]
    return chunk.id


def _fuse_retrieval_results(
    semantic_matches: list[dict],
    lexical_matches: list[dict],
) -> list[dict]:
    """Fuse semantic and lexical ranked lists via RRF (Reciprocal Rank Fusion).

    rrf_score = sum(1 / (k + rank))  for each list where the chunk appears.
    k = _RRF_K (60).  Rank is 1-based.
    """
    if not semantic_matches and not lexical_matches:
        return []
    if not semantic_matches:
        fused = _apply_rrf_to_single_list(lexical_matches)
        return fused
    if not lexical_matches:
        fused = _apply_rrf_to_single_list(semantic_matches)
        return fused

    # Both non-empty → full RRF fusion.
    scores: dict[int, float] = {}
    sources: dict[int, set[str]] = {}
    items: dict[int, dict] = {}

    for rank, item in enumerate(semantic_matches, start=1):
        key = _dedup_key(item)
        scores[key] = scores.get(key, 0.0) + 1.0 / (_RRF_K + rank)
        sources.setdefault(key, set()).add("semantic")
        if key not in items:
            items[key] = {
                "chunk": item["chunk"],
                "file_name": item["file_name"],
                "folder_id": item["folder_id"],
                "score": 0.0,
                "source": "",
                "matched_query_index": int(item.get("matched_query_index", -1)),
            }

    for rank, item in enumerate(lexical_matches, start=1):
        key = _dedup_key(item)
        scores[key] = scores.get(key, 0.0) + 1.0 / (_RRF_K + rank)
        sources.setdefault(key, set()).add("lexical")
        if key not in items:
            items[key] = {
                "chunk": item["chunk"],
                "file_name": item["file_name"],
                "folder_id": item["folder_id"],
                "score": 0.0,
                "source": "",
                "matched_query_index": int(item.get("matched_query_index", -1)),
            }

    for key in items:
        src = sources.get(key, set())
        if src == {"semantic", "lexical"}:
            source_tag = "hybrid"
        elif "semantic" in src:
            source_tag = "semantic"
        else:
            source_tag = "lexical"
        items[key]["score"] = scores[key]
        items[key]["source"] = source_tag

    fused = list(items.values())
    fused.sort(key=lambda it: it["score"], reverse=True)
    return fused


def _apply_rrf_to_single_list(matches: list[dict]) -> list[dict]:
    """When only one list exists, assign RRF scores so downstream logic stays uniform."""
    source_tag = "semantic" if matches and _is_semantic(matches[0]) else "lexical"
    result = []
    for rank, item in enumerate(matches, start=1):
        result.append({
            "chunk": item["chunk"],
            "file_name": item["file_name"],
            "folder_id": item["folder_id"],
            "score": 1.0 / (_RRF_K + rank),
            "source": source_tag,
            "matched_query_index": int(item.get("matched_query_index", -1)),
        })
    return result


def _is_semantic(item: dict) -> bool:
    """Heuristic to tag source when only one list is present."""
    return "source" in item and item["source"] == "semantic"


def _rerank_matches(
    matches: list[dict],
    *,
    question: str,
    rerank_enabled: bool,
    rerank_top_n: int,
    rerank_model_name: str,
) -> tuple[list[dict], bool]:
    """Rerank fused matches using a local cross-encoder (optional).

    Requires the optional ``sentence-transformers`` package (and its PyTorch stack),
    which is **not** installed in the default API image to keep builds small on
    CPU-only servers. When the package is missing, reranking is skipped.

    Returns (reranked_matches, rerank_applied).
    - If rerank_enabled is False, returns (matches, False).
    - If model load or scoring fails, falls back to (matches, False).
    """
    if not rerank_enabled or not matches or not question.strip():
        return list(matches), False

    try:
        from sentence_transformers import CrossEncoder  # noqa: PLC0415
    except ImportError:
        logger.info("sentence-transformers not installed; skipping rerank")
        return list(matches), False

    # Module-level model cache
    if not hasattr(_rerank_matches, "_model_cache"):
        _rerank_matches._model_cache = {}  # type: ignore[attr-defined]
        _rerank_matches._model_lock = False  # type: ignore[attr-defined]

    cache = _rerank_matches._model_cache
    model = cache.get(rerank_model_name)
    if model is None:
        try:
            model = CrossEncoder(rerank_model_name, max_length=512)
            cache[rerank_model_name] = model
        except Exception:
            logger.exception("Failed to load rerank model '%s'", rerank_model_name)
            return list(matches), False

    # Only rerank the top rerank_top_n candidates
    top_n = max(1, rerank_top_n)
    rerank_candidates = matches[:top_n]
    rest = matches[top_n:]
    started = time.perf_counter()
    budget_ms = max(100, int(app_settings.qa_rerank_latency_budget_ms))

    try:
        sentence_pairs = [
            (question, item["chunk"].content or "")
            for item in rerank_candidates
        ]
        scores = model.predict(sentence_pairs, show_progress_bar=False)
    except Exception:
        logger.exception("Rerank scoring failed for model '%s'", rerank_model_name)
        return list(matches), False
    elapsed_ms = (time.perf_counter() - started) * 1000
    if elapsed_ms > budget_ms:
        logger.warning(
            "Rerank latency budget exceeded: model=%s elapsed_ms=%.2f budget_ms=%s",
            rerank_model_name,
            elapsed_ms,
            budget_ms,
        )

    for item, s in zip(rerank_candidates, scores):
        item["rerank_score"] = float(s)

    rerank_candidates.sort(key=lambda it: it.get("rerank_score", 0.0), reverse=True)

    return rerank_candidates + rest, True


MODEL_NON_KB_PREFIX = "以下内容不基于知识库\n\n"


def _compose_kb_user_prompt(
    *,
    base_user_prompt: str,
    query_analysis: dict[str, Any],
    task_type: str,
    selected_reliable_matches: list[dict],
    references: list[dict],
    score_floor: float,
    coverage_diagnostics: dict[str, Any] | None = None,
    strict_mode: bool = False,
) -> tuple[str, dict[str, Any]]:
    """在最终 user prompt 前注入按 query_type 的结构化要求与证据强度提示。"""
    top_rel = max((float(x.get("score", 0.0)) for x in selected_reliable_matches), default=0.0)
    distinct_ref_files = len(
        {int(r.get("file_id")) for r in references if r.get("file_id") is not None}
    )
    sufficiency = assess_evidence_sufficiency(
        references=references,
        reliable_match_count=len(selected_reliable_matches),
        top_reliable_score=top_rel,
        score_floor=score_floor,
        packed_reference_count=len(references),
        distinct_files_in_refs=distinct_ref_files,
    )
    conflict_hint = evidence_conflict_hint(references)
    post_files = distinct_ref_files
    post_dom = 0.0
    if coverage_diagnostics:
        post_files = int(coverage_diagnostics.get("distinct_files_post_pack") or distinct_ref_files)
        post_dom = float(coverage_diagnostics.get("dominant_file_ratio_post_pack") or 0.0)
    else:
        by_f: dict[int, int] = defaultdict(int)
        for r in references:
            if not isinstance(r, dict) or r.get("file_id") is None:
                continue
            try:
                by_f[int(r["file_id"])] += 1
            except (TypeError, ValueError):
                continue
        tot = sum(by_f.values())
        if tot:
            post_dom = max(by_f.values()) / tot
    coverage_assessment = assess_coverage_sufficiency_for_answer(
        query_type=str(query_analysis.get("query_type") or "factual"),
        distinct_files_post_pack=post_files,
        dominant_file_ratio_post_pack=post_dom,
        conflict_hint=conflict_hint,
        coverage_diagnostics=coverage_diagnostics,
    )
    addon, trace = build_answer_synthesis_addon(
        query_type=str(query_analysis.get("query_type") or "factual"),
        task_type=task_type,
        sufficiency=sufficiency,
        conflict_hint=conflict_hint,
        reference_count=len(references),
        distinct_files=distinct_ref_files,
        coverage_assessment=coverage_assessment,
        strict_mode=strict_mode,
    )
    trace["evidence_sufficiency"] = sufficiency
    trace["coverage_sufficiency"] = coverage_assessment
    merged = (addon + "\n\n" + base_user_prompt) if addon else base_user_prompt
    return merged, trace


def _build_context_from_matches(items: list[dict]) -> tuple[list[str], list[dict], list[int]]:
    context_blocks: list[str] = []
    references: list[dict] = []
    used_files: list[int] = []
    for item in items:
        chunk = item["chunk"]
        context_blocks.append(
            f"[文件: {item['file_name']} | chunk: {chunk.chunk_index}]\n{chunk.content}"
        )
        meta = chunk.metadata_json if isinstance(chunk.metadata_json, dict) else {}
        references.append(
            {
                "file_id": chunk.file_id,
                "file_name": item["file_name"],
                "chunk_id": chunk.id,
                "chunk_index": chunk.chunk_index,
                "snippet": _build_snippet(chunk.content),
                "score": item["score"],
                "section_title": chunk.section_title,
                "page_number": chunk.page_number,
                "heading_path": meta.get("heading_path"),
                "block_type": meta.get("block_type"),
                "chunk_role": meta.get("chunk_role"),
            }
        )
        if chunk.file_id not in used_files:
            used_files.append(chunk.file_id)
    return context_blocks, references, used_files


def _qa_chat_completion(settings: SystemSetting, *, system: str, user: str) -> str:
    return chat_completion(
        provider=settings.llm_provider,
        api_base=settings.llm_api_base,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )


def ask_question(
    db: Session,
    *,
    question: str,
    scope_type: str,
    folder_id: int | None,
    file_ids: list[int] | None,
    strict_mode: bool,
    top_k: int,
    candidate_k: int | None = None,
    max_context_chars: int | None = None,
    neighbor_window: int | None = None,
    dedupe_adjacent_chunks: bool | None = None,
    rerank_enabled: bool | None = None,
    rerank_top_n: int | None = None,
    session_id: int | None = None,
    current_user: User | None = None,
) -> dict:
    if scope_type == "files" and not file_ids:
        raise QAServiceError("NO_INDEXED_CONTENT", "当前尚未选择文件范围，请先选择至少一个文件")

    settings = _load_settings(db)
    if not settings.qa_enabled:
        raise QAServiceError("QA_DISABLED", "智能问答尚未启用")
    if not (
        settings.embedding_provider
        and settings.embedding_api_base
        and settings.embedding_api_key
        and settings.embedding_model
    ):
        raise QAServiceError("EMBEDDING_NOT_CONFIGURED", "Embedding 配置不完整，无法执行问答")
    if not (settings.llm_provider and settings.llm_api_base and settings.llm_api_key and settings.llm_model):
        raise QAServiceError("LLM_NOT_CONFIGURED", "LLM 配置不完整，无法执行问答")

    top_k = max(MIN_TOP_K, min(top_k, MAX_TOP_K))
    candidate_k = max(1, candidate_k if candidate_k is not None else app_settings.qa_candidate_k)
    neighbor_window = max(0, neighbor_window if neighbor_window is not None else app_settings.qa_neighbor_window)
    max_context_chars = max(1, max_context_chars if max_context_chars is not None else app_settings.qa_max_context_chars)
    dedupe_adjacent = bool(
        dedupe_adjacent_chunks
        if dedupe_adjacent_chunks is not None
        else app_settings.qa_dedupe_adjacent_chunks
    )
    eff_rerank_enabled = (
        bool(rerank_enabled)
        if rerank_enabled is not None
        else bool(app_settings.qa_rerank_enabled)
    )
    eff_rerank_top_n = (
        max(1, rerank_top_n)
        if rerank_top_n is not None
        else max(1, app_settings.qa_rerank_top_n)
    )
    max_chunks_per_doc = max(1, int(app_settings.qa_max_chunks_per_doc))
    target_distinct_docs = max(1, int(app_settings.qa_target_distinct_docs))
    min_distinct_docs_for_multi = max(1, int(app_settings.qa_min_distinct_docs_for_multi_source))
    single_doc_dominance_ratio = max(1.0, float(app_settings.qa_single_doc_dominance_ratio))
    diversity_rerank_enabled = bool(app_settings.qa_diversity_rerank_enabled)
    diversity_rerank_fetch_k = max(1, int(app_settings.qa_diversity_fetch_k))
    diversity_lambda = float(app_settings.qa_diversity_lambda)
    redundancy_sim_threshold = max(0.0, min(1.0, float(app_settings.qa_redundancy_sim_threshold)))
    redundancy_adjacent_window = max(0, int(app_settings.qa_redundancy_adjacent_window))
    pool_limit = min(QA_RETRIEVAL_POOL_CAP, max(MIN_TOP_K, top_k, candidate_k))

    retrieval_mode = _normalize_retrieval_mode(app_settings.qa_retrieval_mode)
    normalized_query = " ".join((question or "").split()).strip()
    trace_id = uuid.uuid4().hex
    request_id = uuid.uuid4().hex
    input_guardrail = apply_input_guardrail(question)
    routing = route_task_scope_skill(question=question, scope_type=scope_type, file_ids=file_ids)
    task_type = routing["task_type"]
    selected_scope = routing.get("selected_scope", scope_type)
    selected_skill = routing.get("selected_skill")
    compare_targets = routing.get("compare_targets") or []
    query_analysis = build_query_analysis(
        question,
        routing=routing,
        normalized_query=normalized_query,
        base_variants=_build_query_variants(question),
    )
    query_ux_summary = compact_query_trace_for_meta(query_analysis)
    planned = plan_retrieval(
        task_type=task_type,
        normalized_query=normalized_query,
        rewritten_queries=list(query_analysis["retrieval_queries"]),
        scope_type=scope_type,
        strict_mode=strict_mode,
        top_k=top_k,
        candidate_k=candidate_k,
        file_ids=file_ids,
        selected_scope=selected_scope,
        selected_skill=selected_skill,
    )
    query_variants = planned.get("rewritten_queries") or list(query_analysis["retrieval_queries"]) or [normalized_query]
    top_k = max(MIN_TOP_K, min(int(planned.get("top_k", top_k)), MAX_TOP_K))
    candidate_k = max(1, int(planned.get("candidate_k", candidate_k)))
    workflow_steps = list(planned.get("workflow_steps") or [])
    tool_traces = [
        summarize_tool_trace("route_task_scope_skill", routing),
        summarize_tool_trace("input_guardrail", input_guardrail),
        summarize_tool_trace(
            "plan_retrieval",
            {
                "selected_strategy": planned.get("selected_strategy"),
                "top_k": top_k,
                "candidate_k": candidate_k,
                "rewritten_queries": query_variants,
                "scopes": planned.get("scopes"),
                "candidate_plan": planned.get("candidate_plan"),
            },
        ),
        summarize_tool_trace("query_understanding", query_ux_summary),
    ]
    session_context = build_session_context(
        session_id=session_id,
        scope_type=scope_type,
        folder_id=folder_id,
        file_ids=file_ids,
        task_type=task_type,
        compare_targets=compare_targets,
        normalized_query=normalized_query,
        selected_scope=selected_scope,
        selected_skill=selected_skill,
        planner_summary={
            "strategy": planned.get("selected_strategy"),
            "queries": query_variants,
            "query_type": query_analysis.get("query_type"),
            "multi_query_merge": query_analysis.get("multi_query_merge_used"),
        },
    )
    if task_type == TASK_CLARIFICATION_NEEDED:
        clarification_text = "当前问题需要先澄清比较对象或范围。请在下一条消息明确：比较对象A/B，或指定文件/目录范围。"
        workflow_steps.append({"step": "clarify_skill_triggered", "status": "completed"})
        tool_traces.append(summarize_tool_trace("clarify_skill", {"triggered": True, "reason": routing.get("task_reason")}))
        retrieval_meta = _build_retrieval_meta(
            retrieval_strategy=DEFAULT_RETRIEVAL_STRATEGY,
            answer_source="knowledge_base_low_confidence",
            scope_type=scope_type,
            strict_mode=strict_mode,
            top_k=top_k,
            compatible_file_count=0,
            candidate_chunks=0,
            matched_chunks=0,
            selected_chunks=0,
            used_file_ids=[],
            candidate_k=candidate_k,
            expanded_chunks=0,
            packed_chunks=0,
            context_chars=0,
            neighbor_window=neighbor_window,
            dedupe_adjacent_chunks=dedupe_adjacent,
            retrieval_mode=retrieval_mode,
            semantic_candidate_count=0,
            lexical_candidate_count=0,
            fusion_method="none",
            score_threshold_applied=MIN_SIMILARITY_SCORE,
            rerank_enabled=eff_rerank_enabled,
            rerank_input_count=0,
            rerank_output_count=0,
            rerank_model_name=app_settings.qa_rerank_model_name,
            rerank_applied=False,
            normalized_query=normalized_query,
            rewritten_queries=query_variants,
            abstain_reason="问题需要澄清后再检索",
            abstain_reason_code=QAReasonCode.INSUFFICIENT_EVIDENCE.value,
            trace_id=trace_id,
            request_id=request_id,
            task_type=task_type,
            planner_output=planned,
            selected_strategy=planned.get("selected_strategy"),
            workflow_steps_json=workflow_steps,
            tool_traces_json=tool_traces,
            session_context_json=session_context,
            final_answer_type="clarification_needed",
            selected_scope=selected_scope,
            selected_skill=selected_skill,
            clarification_needed=True,
            workflow_summary="clarify_before_retrieval",
            source_count=0,
            dominant_source_ratio=0.0,
            multi_source_coverage=0.0,
            fallback_triggered=False,
            retrieval_rounds=0,
            stop_reason="clarification_required",
            query_understanding_summary=query_ux_summary,
        )
        return {
            "answer": clarification_text,
            "references": [],
            "references_json": {"answer_source": "knowledge_base_low_confidence", "references": []},
            "evidence_bundles": None,
            "answer_source": "knowledge_base_low_confidence",
            "used_files": [],
            "retrieval_meta": retrieval_meta,
            "task_type": task_type,
            "selected_skill": selected_skill,
            "planner_meta": planned,
            "compare_result": None,
            "clarification_needed": True,
            "workflow_summary": "clarify_before_retrieval",
        }
    try:
        query_embeddings = embed_texts(
            provider=settings.embedding_provider,
            api_base=settings.embedding_api_base,
            api_key=settings.embedding_api_key,
            model=settings.embedding_model,
            inputs=query_variants,
            embedding_batch_size_from_db=settings.embedding_batch_size,
        )
    except RuntimeError as exc:
        raise _qa_model_runtime_error("embed", exc) from exc
    if not query_embeddings:
        raise QAServiceError("EMBEDDING_DATA_UNAVAILABLE", "查询向量为空，无法执行检索")

    compatible_file_ids = _collect_retrievable_file_ids(
        db,
        settings=settings,
        scope_type=scope_type,
        folder_id=folder_id,
        file_ids=file_ids,
        expected_dimension=len(query_embeddings[0]),
        current_user=current_user,
    )
    if not compatible_file_ids:
        if strict_mode:
            raise QAServiceError(
                "NO_COMPATIBLE_INDEXED_CONTENT",
                "当前范围内没有可用于当前知识库索引标准的已索引文献，请先建立或重建索引。",
            )
        user_prompt = (
            "当前问答范围内没有可用于当前知识库索引标准的已索引文献，无法从知识库取得任何可引用片段。\n"
            "请基于你的通用知识直接回答用户问题。\n"
            "要求：不要虚构本知识库中的文献或条文；不要使用「根据上传文件」「资料中记载」等表述。\n\n"
            f"问题：{question}"
        )
        system_msg = (
            "用户处于非严格问答模式，且当前范围内没有可检索的知识库内容；请用通用知识作答，切勿伪造知识库引用。"
        )
        try:
            answer = _qa_chat_completion(settings, system=system_msg, user=user_prompt)
        except RuntimeError as exc:
            raise _qa_model_runtime_error("chat", exc) from exc
        answer = MODEL_NON_KB_PREFIX + answer
        refs_payload = {"answer_source": "model_general", "references": []}
        retrieval_meta = _build_retrieval_meta(
            retrieval_strategy=DEFAULT_RETRIEVAL_STRATEGY,
            answer_source="model_general",
            scope_type=scope_type,
            strict_mode=strict_mode,
            top_k=top_k,
            compatible_file_count=0,
            candidate_chunks=0,
            matched_chunks=0,
            selected_chunks=0,
            used_file_ids=[],
            candidate_k=candidate_k,
            expanded_chunks=0,
            packed_chunks=0,
            context_chars=0,
            neighbor_window=neighbor_window,
            dedupe_adjacent_chunks=dedupe_adjacent,
            retrieval_mode=retrieval_mode,
            semantic_candidate_count=0,
            lexical_candidate_count=0,
            fusion_method="none",
            score_threshold_applied=MIN_SIMILARITY_SCORE,
            rerank_enabled=eff_rerank_enabled,
            rerank_input_count=0,
            rerank_output_count=0,
            rerank_model_name=app_settings.qa_rerank_model_name,
            rerank_applied=False,
            parent_recovered_chunks=0,
            parent_deduped_groups=0,
            normalized_query=normalized_query,
            rewritten_queries=query_variants,
            abstain_reason="未检索到可用知识片段",
            abstain_reason_code=QAReasonCode.NO_RETRIEVAL_HIT.value,
            trace_id=trace_id,
            request_id=request_id,
            task_type=task_type,
            planner_output=planned,
            selected_strategy=planned.get("selected_strategy"),
            workflow_steps_json=workflow_steps,
            tool_traces_json=tool_traces,
            session_context_json=session_context,
            final_answer_type="model_general",
            selected_scope=selected_scope,
            selected_skill=selected_skill,
            planner_meta=planned,
            clarification_needed=False,
            workflow_summary="abstain_or_general_fallback",
            source_count=0,
            dominant_source_ratio=0.0,
            multi_source_coverage=0.0,
            fallback_triggered=False,
            retrieval_rounds=0,
            stop_reason="insufficient_after_round1",
            query_understanding_summary=query_ux_summary,
        )
        return {
            "answer": answer,
            "references": [],
            "references_json": refs_payload,
            "evidence_bundles": None,
            "answer_source": "model_general",
            "used_files": [],
            "retrieval_meta": retrieval_meta,
        }

    retrieval_strategy = DEFAULT_RETRIEVAL_STRATEGY
    semantic_matches: list[dict] = []
    lexical_matches: list[dict] = []
    if retrieval_mode in {"semantic", "hybrid"}:
        semantic_matches, semantic_strategy = _semantic_retrieval(
            db,
            query_embeddings=query_embeddings,
            compatible_file_ids=compatible_file_ids,
            top_k=pool_limit,
        )
        retrieval_strategy = semantic_strategy
    if retrieval_mode in {"lexical", "hybrid"}:
        lexical_matches = _lexical_retrieval(
            db,
            questions=query_variants,
            compatible_file_ids=compatible_file_ids,
            top_k=pool_limit,
        )
    if retrieval_mode == "semantic":
        matches = semantic_matches
    elif retrieval_mode == "lexical":
        matches = _apply_rrf_to_single_list(lexical_matches)
        retrieval_strategy = "fts_websearch_rrf"
    else:
        matches = _fuse_retrieval_results(semantic_matches, lexical_matches)

    # --- Rerank ---
    rerank_input_count = len(matches)
    matches, rerank_applied = _rerank_matches(
        matches,
        question=question,
        rerank_enabled=eff_rerank_enabled,
        rerank_top_n=eff_rerank_top_n,
        rerank_model_name=app_settings.qa_rerank_model_name,
    )
    unique_docs_before_diversity = len({_doc_key(item) for item in matches})
    matches, diversity_applied = _diversity_rerank_matches(
        matches,
        enabled=diversity_rerank_enabled,
        diversity_lambda=diversity_lambda,
        fetch_k=diversity_rerank_fetch_k,
        redundancy_sim_threshold=redundancy_sim_threshold,
    )
    unique_docs_after_diversity = len({_doc_key(item) for item in matches})
    rerank_output_count = len(matches)

    candidate_matches = _truncate_ranked_to_candidate_k(matches, candidate_k)
    score_threshold_applied = _score_threshold_for_mode(retrieval_mode)
    reliable_matches = [item for item in candidate_matches if item["score"] >= score_threshold_applied]
    retrieval_rounds = 1
    fallback_triggered = False
    coverage_seed_metrics = _compute_source_coverage_metrics([{"file_id": int(item["chunk"].file_id)} for item in reliable_matches], top_k=top_k)
    initial_coverage_decision = _evaluate_coverage_decision(task_type=task_type, metrics=coverage_seed_metrics, retrieval_rounds=1, max_rounds=int(planned.get("max_retrieval_rounds", 2)))
    if (not reliable_matches or initial_coverage_decision.get("action") == "fallback") and bool(planned.get("fallback_enabled")):
        fallback_triggered = True
        retrieval_rounds = 2
        fallback_plan = (planned.get("candidate_plan") or [{}, {}])[1]
        fallback_queries = fallback_plan.get("queries") or query_variants[:1]
        try:
            fallback_embeddings = embed_texts(
                provider=settings.embedding_provider,
                api_base=settings.embedding_api_base,
                api_key=settings.embedding_api_key,
                model=settings.embedding_model,
                inputs=fallback_queries,
                embedding_batch_size_from_db=settings.embedding_batch_size,
            )
        except RuntimeError:
            fallback_embeddings = []
        if fallback_embeddings:
            tool_traces.append(summarize_tool_trace("retrieval_fallback_gate", {"triggered": True, "reason": "coverage_or_reliability", "initial_coverage": initial_coverage_decision}))
            fb_semantic, _ = _semantic_retrieval(
                db,
                query_embeddings=fallback_embeddings,
                compatible_file_ids=compatible_file_ids,
                top_k=min(pool_limit + 2, QA_RETRIEVAL_POOL_CAP),
            )
            fb_lexical = _lexical_retrieval(
                db,
                questions=fallback_queries,
                compatible_file_ids=compatible_file_ids,
                top_k=min(pool_limit + 2, QA_RETRIEVAL_POOL_CAP),
            )
            fallback_matches = _fuse_retrieval_results(fb_semantic, fb_lexical)
            fallback_matches, _ = _rerank_matches(
                fallback_matches,
                question=question,
                rerank_enabled=eff_rerank_enabled,
                rerank_top_n=eff_rerank_top_n,
                rerank_model_name=app_settings.qa_rerank_model_name,
            )
            if fallback_matches:
                candidate_matches = _truncate_ranked_to_candidate_k(fallback_matches, candidate_k)
                reliable_matches = [item for item in candidate_matches if item["score"] >= score_threshold_applied]
                tool_traces.append(
                    summarize_tool_trace(
                        "retrieval_fallback_round",
                        {
                            "triggered": True,
                            "queries": fallback_queries,
                            "reliable_matches": len(reliable_matches),
                        },
                    )
                )
    distinct_docs_in_topk = len({_doc_key(item) for item in candidate_matches})
    dominance_guardrail_triggered = _dominance_guardrail(
        reliable_matches,
        dominance_ratio=single_doc_dominance_ratio,
    )
    allow_single_doc_dominance = dominance_guardrail_triggered or (
        len({_doc_key(item) for item in reliable_matches}) < min_distinct_docs_for_multi
    )
    selected_reliable_matches = _select_doc_aware_matches(
        reliable_matches,
        max_chunks_per_doc=max_chunks_per_doc,
        target_distinct_docs=target_distinct_docs,
        top_k=top_k,
        allow_single_doc_dominance=allow_single_doc_dominance,
    )
    per_doc_selected: dict[int, list[int]] = defaultdict(list)
    for item in selected_reliable_matches:
        per_doc_selected[int(item["chunk"].file_id)].append(int(item["chunk"].chunk_index))
    source_count = len(per_doc_selected)
    dominant_source_ratio = (
        max((len(v) for v in per_doc_selected.values()), default=0) / max(1, len(selected_reliable_matches))
    )
    multi_source_coverage = source_count / max(1, min(top_k, 3))
    compatible_count = len(compatible_file_ids)
    stop_reason = "enough_evidence" if selected_reliable_matches else (
        "fallback_triggered_but_insufficient" if fallback_triggered else "insufficient_after_round1"
    )
    if task_type == TASK_COMPARE and source_count <= 1:
        stop_reason = "compare_evidence_asymmetric"
    source_skew_detected = source_count > 0 and dominant_source_ratio >= 0.8
    if source_skew_detected:
        workflow_steps.append({"step": "single_source_skew_detected", "status": "warning"})
        tool_traces.append(
            summarize_tool_trace(
                "single_source_skew_warning",
                {
                    "source_count": source_count,
                    "dominant_source_ratio": dominant_source_ratio,
                    "multi_source_coverage": multi_source_coverage,
                },
            )
        )
    logger.info(
        "QA retrieval mode=%s strategy=%s compatible_files=%s semantic=%s lexical=%s fused=%s reliable=%s selected=%s threshold=%.4f rerank=%s diversity=%s unique_docs_before=%s unique_docs_after=%s dominance=%s per_doc=%s",
        retrieval_mode,
        retrieval_strategy,
        compatible_count,
        len(semantic_matches),
        len(lexical_matches),
        len(matches),
        len(reliable_matches),
        len(selected_reliable_matches),
        score_threshold_applied,
        rerank_applied,
        diversity_applied,
        unique_docs_before_diversity,
        unique_docs_after_diversity,
        dominance_guardrail_triggered,
        dict(per_doc_selected),
    )

    ux_query_type = str(query_analysis.get("query_type") or "factual")
    coverage_diagnostics_last: dict[str, Any] | None = None

    try:
        if strict_mode:
            if not candidate_matches:
                raise QAServiceError(
                    "NO_RELIABLE_EVIDENCE",
                    "知识库中未检索到可用资料，严格模式下无法回答。",
                )
            if not reliable_matches:
                raise QAServiceError(
                    "NO_RELIABLE_EVIDENCE",
                    "知识库中未找到足够相关的依据，严格模式下无法回答。",
                )
            expanded_items = _expand_neighbor_chunks(db, selected_reliable_matches, neighbor_window)
            expanded_n = len(expanded_items)
            deduped_items = _dedupe_chunk_items(expanded_items)
            # coverage 流水线：先限制同 parent 子块数，再回收 parent 正文；neighbor 已带 source_reason / matched_query_index
            deduped_items = _cap_children_per_parent(deduped_items, app_settings.qa_max_children_per_parent)
            pack_items, parent_deduped_groups = _recover_parent_context_for_packing(db, deduped_items)
            _expand_adjacent_parent_context(db, pack_items)
            # 相邻 parent 仅追加正文，matched_query_index 仍继承代表子块（检索命中链不断档）
            pack_items, qa_retrieval_trace = _prepare_pack_items_with_diversification(
                pack_items,
                selected_reliable_matches=selected_reliable_matches,
                deduped_expanded_count=len(deduped_items),
                query_type=ux_query_type,
            )
            # qa_enable_coverage_aware_packing 时此处走 select_pack_items_coverage_two_phase（见 _prepare_pack_items_with_diversification）
            packing_trace: dict[str, Any] | None = {} if _want_packing_trace_dict() else None
            seed_ids = {item["chunk"].id for item in selected_reliable_matches}
            (
                context_blocks,
                references,
                used_files,
                context_chars,
                packed_n,
                parent_recovered_chunks,
                adjacent_chunk_redundancy_rate,
            ) = _pack_context_and_references(
                pack_items,
                seed_chunk_ids=seed_ids,
                max_context_chars=max_context_chars,
                dedupe_adjacent_chunks=dedupe_adjacent,
                redundancy_sim_threshold=redundancy_sim_threshold,
                redundancy_adjacent_window=redundancy_adjacent_window,
                packing_trace=packing_trace,
                query_type=ux_query_type,
                retrieval_queries=query_variants,
            )
            if qa_retrieval_trace is not None and packing_trace is not None:
                qa_retrieval_trace["packing"] = packing_trace
            if packed_n < max(1, int(app_settings.qa_strict_min_citations)):
                logger.info("strict evidence decision=reject reason=insufficient_citations packed=%s", packed_n)
                raise QAServiceError(
                    "NO_RELIABLE_EVIDENCE",
                    "知识库证据不足，严格模式下无法给出可引用回答。",
                )
            evidence_guardrail = apply_evidence_guardrail(references)
            tool_traces.append(summarize_tool_trace("evidence_guardrail", evidence_guardrail))
            base_kb_prompt = (
                "你是实验室内部知识库问答助手。你只允许根据下方「资料片段」回答问题。\n"
                "要求：\n"
                "- 结论必须可由资料支撑；不要引入资料未提及的关键事实。\n"
                "- 若单一来源证据已完整充分，可基于该来源作答；若多来源互补，请综合多来源关键信息。\n"
                "- 若资料不足以回答用户问题，请明确说明无法根据当前知识库资料作出完整回答，不要猜测，"
                "也不要改用通用知识或常识来替代知识库依据。\n\n"
                f"问题：{question}\n\n资料片段：\n"
                + "\n\n".join(context_blocks)
            )
            coverage_diagnostics = None
            if bool(app_settings.qa_enable_coverage_diagnostics) and references:
                coverage_diagnostics = build_coverage_diagnostics_payload(
                    pre_pack_items=list(pack_items),
                    references=references,
                    retrieval_queries=list(query_variants),
                    reliable_matches=reliable_matches,
                    query_type=ux_query_type,
                    coverage_select_trace=(qa_retrieval_trace or {}).get("coverage_selection"),
                    packing_trace=packing_trace,
                    compare_side_hint=_compare_side_coverage_hint(compare_targets, references)
                    if task_type == TASK_COMPARE
                    else None,
                )
            coverage_diagnostics_last = coverage_diagnostics
            user_prompt, answer_synthesis_trace = _compose_kb_user_prompt(
                base_user_prompt=base_kb_prompt,
                query_analysis=query_analysis,
                task_type=task_type,
                selected_reliable_matches=selected_reliable_matches,
                references=references,
                score_floor=score_threshold_applied,
                coverage_diagnostics=coverage_diagnostics,
                strict_mode=True,
            )
            system_msg = (
                "你是一个只依据用户给定的知识库片段作答的助手；无充分依据时不臆测，也不使用课外知识兜底。"
            )
            answer = _qa_chat_completion(settings, system=system_msg, user=user_prompt)
            if source_skew_detected:
                answer = "说明：当前结论主要来自单一来源，建议结合更多资料复核。\n" + answer
            output_guardrail = apply_output_guardrail(answer=answer, references=references, compare_mode=task_type == TASK_COMPARE)
            tool_traces.append(summarize_tool_trace("output_guardrail", output_guardrail))
            if not _is_grounded_answer(answer, references):
                logger.info("strict evidence decision=reject reason=grounding_guard")
                raise QAServiceError(
                    "NO_RELIABLE_EVIDENCE",
                    "知识库证据不足，严格模式下无法给出可引用回答。",
                )
            if task_type == TASK_COMPARE:
                workflow_steps.append({"step": "compare_evidence_sets", "status": "completed"})
            coverage_metrics = _compute_source_coverage_metrics(references, top_k=top_k)
            coverage_decision = _evaluate_coverage_decision(task_type=task_type, metrics=coverage_metrics, retrieval_rounds=retrieval_rounds, max_rounds=int(planned.get("max_retrieval_rounds", 2)))
            tool_traces.append(summarize_tool_trace("coverage_policy", coverage_decision))
            compare_result_payload = _build_compare_result(compare_targets, references) if task_type == TASK_COMPARE else None
            if task_type == TASK_COMPARE and compare_result_payload and (not compare_result_payload.get("evidence_sufficiency") or compare_result_payload.get("evidence_asymmetry")):
                answer = "说明：当前比较存在证据不对称，结论需谨慎。\n" + answer
            if coverage_decision.get("single_source_skew"):
                answer = "说明：当前回答存在单源倾斜，请结合更多来源复核。\n" + answer
            elif task_type == TASK_MULTI_DOC_SYNTHESIS:
                workflow_steps.append({"step": "synthesize_with_citations", "status": "completed"})
            logger.info("strict evidence decision=accept citations=%s", len(references))
            retrieval_meta = _build_retrieval_meta(
                retrieval_strategy=retrieval_strategy,
                answer_source="knowledge_base",
                scope_type=scope_type,
                strict_mode=strict_mode,
                top_k=top_k,
                compatible_file_count=compatible_count,
                candidate_chunks=len(matches),
                matched_chunks=len(reliable_matches),
                selected_chunks=packed_n,
                used_file_ids=list(used_files),
                candidate_k=candidate_k,
                expanded_chunks=expanded_n,
                packed_chunks=packed_n,
                context_chars=context_chars,
                neighbor_window=neighbor_window,
                dedupe_adjacent_chunks=dedupe_adjacent,
                retrieval_mode=retrieval_mode,
                semantic_candidate_count=len(semantic_matches),
                lexical_candidate_count=len(lexical_matches),
                fusion_method=("rrf" if retrieval_mode == "hybrid" else retrieval_mode),
                score_threshold_applied=score_threshold_applied,
                rerank_enabled=eff_rerank_enabled,
                rerank_input_count=rerank_input_count,
                rerank_output_count=rerank_output_count,
                rerank_model_name=app_settings.qa_rerank_model_name,
                rerank_applied=rerank_applied,
                parent_recovered_chunks=parent_recovered_chunks,
                parent_deduped_groups=parent_deduped_groups,
                distinct_docs_in_topk=distinct_docs_in_topk,
                distinct_docs_in_context=len(set(used_files)),
                same_doc_chunk_ratio=((packed_n - len(set(used_files))) / packed_n if packed_n else 0.0),
                adjacent_chunk_redundancy_rate=adjacent_chunk_redundancy_rate,
                dominance_guardrail_triggered=dominance_guardrail_triggered,
                diversity_rerank_enabled=diversity_rerank_enabled,
                diversity_rerank_applied=diversity_applied,
                diversity_rerank_fetch_k=diversity_rerank_fetch_k,
                normalized_query=normalized_query,
                rewritten_queries=query_variants,
                trace_id=trace_id,
                request_id=request_id,
                task_type=task_type,
                planner_output=planned,
                selected_strategy=planned.get("selected_strategy"),
                workflow_steps_json=workflow_steps,
                tool_traces_json=tool_traces,
                session_context_json=session_context,
                final_answer_type=("compare" if task_type == TASK_COMPARE else "knowledge_base"),
                selected_scope=selected_scope,
                selected_skill=selected_skill,
                planner_meta={
                    **planned,
                    "retrieval_rounds": retrieval_rounds,
                    "fallback_triggered": fallback_triggered,
                    "stop_reason": stop_reason,
                    "coverage_policy_decision": coverage_decision,
                    **coverage_metrics,
                },
                compare_result=compare_result_payload,
                clarification_needed=False,
                workflow_summary=("compare_skill" if task_type == TASK_COMPARE else selected_skill),
                source_count=int(coverage_metrics["source_count"]),
                dominant_source_ratio=float(coverage_metrics["dominant_source_ratio"]),
                multi_source_coverage=float(coverage_metrics["multi_source_coverage"]),
                fallback_triggered=fallback_triggered,
                retrieval_rounds=retrieval_rounds,
                stop_reason=stop_reason,
                retrieval_trace=qa_retrieval_trace,
                query_understanding_summary=query_ux_summary,
                answer_synthesis_trace=answer_synthesis_trace,
                coverage_diagnostics=coverage_diagnostics,
            )
            evidence_bundles = _assemble_evidence_bundles(references)
            return {
                "answer": answer,
                "references": references,
                "references_json": references,
                "evidence_bundles": evidence_bundles,
                "answer_source": "knowledge_base",
                "used_files": used_files,
                "retrieval_meta": retrieval_meta,
            }

        if selected_reliable_matches:
            expanded_items = _expand_neighbor_chunks(db, selected_reliable_matches, neighbor_window)
            expanded_n = len(expanded_items)
            deduped_items = _dedupe_chunk_items(expanded_items)
            deduped_items = _cap_children_per_parent(deduped_items, app_settings.qa_max_children_per_parent)
            pack_items, parent_deduped_groups = _recover_parent_context_for_packing(db, deduped_items)
            _expand_adjacent_parent_context(db, pack_items)
            pack_items, qa_retrieval_trace = _prepare_pack_items_with_diversification(
                pack_items,
                selected_reliable_matches=selected_reliable_matches,
                deduped_expanded_count=len(deduped_items),
                query_type=ux_query_type,
            )
            packing_trace_ns: dict[str, Any] | None = {} if _want_packing_trace_dict() else None
            seed_ids = {item["chunk"].id for item in selected_reliable_matches}
            (
                context_blocks,
                references,
                used_files,
                context_chars,
                packed_n,
                parent_recovered_chunks,
                adjacent_chunk_redundancy_rate,
            ) = _pack_context_and_references(
                pack_items,
                seed_chunk_ids=seed_ids,
                max_context_chars=max_context_chars,
                dedupe_adjacent_chunks=dedupe_adjacent,
                redundancy_sim_threshold=redundancy_sim_threshold,
                redundancy_adjacent_window=redundancy_adjacent_window,
                packing_trace=packing_trace_ns,
                query_type=ux_query_type,
                retrieval_queries=query_variants,
            )
            if qa_retrieval_trace is not None and packing_trace_ns is not None:
                qa_retrieval_trace["packing"] = packing_trace_ns
            evidence_guardrail = apply_evidence_guardrail(references)
            tool_traces.append(summarize_tool_trace("evidence_guardrail", evidence_guardrail))
            if task_type == TASK_MULTI_DOC_SYNTHESIS:
                base_kb_prompt = (
                    "你是实验室知识库问答助手。请做多来源综合并保留引用意识。\n"
                    "要求：\n"
                    "- 先按主题归纳关键信息，再给总结。\n"
                    "- 关键结论必须由资料支撑；若证据冲突，要明确指出冲突。\n"
                    "- 若证据不足，明确说明局限并保守回答。\n\n"
                    f"问题：{question}\n\n资料片段：\n"
                    + "\n\n".join(context_blocks)
                )
            elif task_type == TASK_COMPARE:
                base_kb_prompt = (
                    "你是实验室知识库比较助手。请基于资料输出结构化比较。\n"
                    "输出格式：\n"
                    "1) 比较对象\n2) 共同点\n3) 差异点\n4) 冲突点/证据不足\n5) 结论\n"
                    "要求：仅依据资料，不要臆测。\n\n"
                    f"问题：{question}\n\n资料片段：\n"
                    + "\n\n".join(context_blocks)
                )
            else:
                base_kb_prompt = (
                    "你是实验室知识库问答助手。请优先根据下方「资料片段」回答问题。\n"
                    "要求：\n"
                    "- 当资料足以支撑结论时，以资料为准，回答应体现资料中的要点。\n"
                    "- 若多个来源提供互补证据，优先综合多个来源；避免机械重复同一来源的连续片段。\n"
                    "- 若单一来源已完整覆盖问题，可直接基于该来源回答。\n"
                    "- 若资料仅有部分相关信息，可先说明资料中的依据，再在必要时少量结合常识补充，"
                    "但不要与资料矛盾，也不要虚构资料中不存在的内容或引用。\n"
                    "- 若资料明显不足以判断用户问题，请说明资料局限，不要假装资料已覆盖。\n\n"
                    f"问题：{question}\n\n资料片段：\n"
                    + "\n\n".join(context_blocks)
                )
            coverage_diagnostics = None
            if bool(app_settings.qa_enable_coverage_diagnostics) and references:
                coverage_diagnostics = build_coverage_diagnostics_payload(
                    pre_pack_items=list(pack_items),
                    references=references,
                    retrieval_queries=list(query_variants),
                    reliable_matches=reliable_matches,
                    query_type=ux_query_type,
                    coverage_select_trace=(qa_retrieval_trace or {}).get("coverage_selection"),
                    packing_trace=packing_trace_ns,
                    compare_side_hint=_compare_side_coverage_hint(compare_targets, references)
                    if task_type == TASK_COMPARE
                    else None,
                )
            coverage_diagnostics_last = coverage_diagnostics
            user_prompt, answer_synthesis_trace = _compose_kb_user_prompt(
                base_user_prompt=base_kb_prompt,
                query_analysis=query_analysis,
                task_type=task_type,
                selected_reliable_matches=selected_reliable_matches,
                references=references,
                score_floor=score_threshold_applied,
                coverage_diagnostics=coverage_diagnostics,
                strict_mode=False,
            )
            system_msg = (
                "你优先依据用户提供的知识库资料作答；仅在资料边界清晰的前提下可谨慎补充常识，不伪造知识库内容。"
            )
            answer = _qa_chat_completion(settings, system=system_msg, user=user_prompt)
            if source_skew_detected:
                answer = "说明：当前结论主要来自单一来源，建议结合更多资料复核。\n" + answer
            output_guardrail = apply_output_guardrail(answer=answer, references=references, compare_mode=task_type == TASK_COMPARE)
            tool_traces.append(summarize_tool_trace("output_guardrail", output_guardrail))
            min_citations = max(1, int(app_settings.qa_min_grounded_citations))
            if len(references) < min_citations or not _is_grounded_answer(answer, references):
                logger.info(
                    "Grounding guard triggered; references=%s required=%s; fallback to model_general",
                    len(references),
                    min_citations,
                )
                reliable_matches = []
            else:
                logger.info("non-strict evidence decision=accept citations=%s", len(references))
                if task_type == TASK_COMPARE:
                    workflow_steps.append({"step": "compare_evidence_sets", "status": "completed"})
                coverage_metrics = _compute_source_coverage_metrics(references, top_k=top_k)
                coverage_decision = _evaluate_coverage_decision(
                    task_type=task_type,
                    metrics=coverage_metrics,
                    retrieval_rounds=retrieval_rounds,
                    max_rounds=int(planned.get("max_retrieval_rounds", 2)),
                )
                tool_traces.append(summarize_tool_trace("coverage_policy", coverage_decision))
                compare_result_payload = _build_compare_result(compare_targets, references) if task_type == TASK_COMPARE else None
                if task_type == TASK_COMPARE and compare_result_payload and (
                    not compare_result_payload.get("evidence_sufficiency") or compare_result_payload.get("evidence_asymmetry")
                ):
                    answer = "说明：当前比较存在证据不对称，结论需谨慎。\n" + answer
                if coverage_decision.get("single_source_skew"):
                    answer = "说明：当前回答存在单源倾斜，请结合更多来源复核。\n" + answer
                elif task_type == TASK_MULTI_DOC_SYNTHESIS:
                    workflow_steps.append({"step": "synthesize_with_citations", "status": "completed"})
                retrieval_meta = _build_retrieval_meta(
                    retrieval_strategy=retrieval_strategy,
                    answer_source="knowledge_base",
                    scope_type=scope_type,
                    strict_mode=strict_mode,
                    top_k=top_k,
                    compatible_file_count=compatible_count,
                    candidate_chunks=len(matches),
                    matched_chunks=len(reliable_matches),
                    selected_chunks=packed_n,
                    used_file_ids=list(used_files),
                    candidate_k=candidate_k,
                    expanded_chunks=expanded_n,
                    packed_chunks=packed_n,
                    context_chars=context_chars,
                    neighbor_window=neighbor_window,
                    dedupe_adjacent_chunks=dedupe_adjacent,
                    retrieval_mode=retrieval_mode,
                    semantic_candidate_count=len(semantic_matches),
                    lexical_candidate_count=len(lexical_matches),
                    fusion_method=("rrf" if retrieval_mode == "hybrid" else retrieval_mode),
                    score_threshold_applied=score_threshold_applied,
                    rerank_enabled=eff_rerank_enabled,
                    rerank_input_count=rerank_input_count,
                    rerank_output_count=rerank_output_count,
                    rerank_model_name=app_settings.qa_rerank_model_name,
                    rerank_applied=rerank_applied,
                    parent_recovered_chunks=parent_recovered_chunks,
                    parent_deduped_groups=parent_deduped_groups,
                    distinct_docs_in_topk=distinct_docs_in_topk,
                    distinct_docs_in_context=len(set(used_files)),
                    same_doc_chunk_ratio=((packed_n - len(set(used_files))) / packed_n if packed_n else 0.0),
                    adjacent_chunk_redundancy_rate=adjacent_chunk_redundancy_rate,
                    dominance_guardrail_triggered=dominance_guardrail_triggered,
                    diversity_rerank_enabled=diversity_rerank_enabled,
                    diversity_rerank_applied=diversity_applied,
                    diversity_rerank_fetch_k=diversity_rerank_fetch_k,
                    normalized_query=normalized_query,
                    rewritten_queries=query_variants,
                    trace_id=trace_id,
                    request_id=request_id,
                    task_type=task_type,
                    planner_output=planned,
                    selected_strategy=planned.get("selected_strategy"),
                    workflow_steps_json=workflow_steps,
                    tool_traces_json=tool_traces,
                    session_context_json=session_context,
                    final_answer_type=("compare" if task_type == TASK_COMPARE else "knowledge_base"),
                    selected_scope=selected_scope,
                    selected_skill=selected_skill,
                    planner_meta={
                        **planned,
                        "retrieval_rounds": retrieval_rounds,
                        "fallback_triggered": fallback_triggered,
                        "stop_reason": stop_reason,
                        "coverage_policy_decision": coverage_decision,
                        **coverage_metrics,
                    },
                    compare_result=compare_result_payload,
                    clarification_needed=False,
                    workflow_summary=("compare_skill" if task_type == TASK_COMPARE else selected_skill),
                    source_count=int(coverage_metrics["source_count"]),
                    dominant_source_ratio=float(coverage_metrics["dominant_source_ratio"]),
                    multi_source_coverage=float(coverage_metrics["multi_source_coverage"]),
                    fallback_triggered=fallback_triggered,
                    retrieval_rounds=retrieval_rounds,
                    stop_reason=stop_reason,
                    retrieval_trace=qa_retrieval_trace,
                    query_understanding_summary=query_ux_summary,
                    answer_synthesis_trace=answer_synthesis_trace,
                    coverage_diagnostics=coverage_diagnostics,
                )
                evidence_bundles = _assemble_evidence_bundles(references)
                return {
                    "answer": answer,
                    "references": references,
                    "references_json": references,
                    "evidence_bundles": evidence_bundles,
                    "answer_source": "knowledge_base",
                    "used_files": used_files,
                    "retrieval_meta": retrieval_meta,
                }

        low_rel_note = ""
        if candidate_matches:
            low_rel_note = (
                "说明：知识库中检索到少量片段，但相似度未达到采用为「知识库依据」的阈值，"
                "故不将检索片段作为引用依据。请完全基于你的通用知识回答，不要引用或编造具体知识库文件名或片段。\n\n"
            )
        user_prompt = (
            "当前没有可作为依据的知识库资料片段供你引用。\n"
            + low_rel_note
            + "请基于你的通用知识直接回答用户问题。\n"
            "要求：不要虚构本知识库中的文献或条文；不要使用「根据上传文件」「资料中记载」等表述。\n\n"
            f"问题：{question}"
        )
        system_msg = (
            "用户处于非严格问答模式，且当前没有可用的知识库片段；请用通用知识作答，切勿伪造知识库引用。"
        )
        answer = _qa_chat_completion(settings, system=system_msg, user=user_prompt)
        answer = MODEL_NON_KB_PREFIX + answer
        low_confidence = bool(candidate_matches)
        answer_src = "knowledge_base_low_confidence" if low_confidence else "model_general"
        logger.info("non-strict evidence decision=fallback answer_source=%s", answer_src)
        refs_payload = {"answer_source": answer_src, "references": []}
        retrieval_meta = _build_retrieval_meta(
            retrieval_strategy=retrieval_strategy,
            answer_source=answer_src,
            scope_type=scope_type,
            strict_mode=strict_mode,
            top_k=top_k,
            compatible_file_count=compatible_count,
            candidate_chunks=len(matches),
            matched_chunks=len(reliable_matches),
            selected_chunks=0,
            used_file_ids=[],
            candidate_k=candidate_k,
            expanded_chunks=0,
            packed_chunks=0,
            context_chars=0,
            neighbor_window=neighbor_window,
            dedupe_adjacent_chunks=dedupe_adjacent,
            retrieval_mode=retrieval_mode,
            semantic_candidate_count=len(semantic_matches),
            lexical_candidate_count=len(lexical_matches),
            fusion_method=("rrf" if retrieval_mode == "hybrid" else retrieval_mode),
            score_threshold_applied=score_threshold_applied,
            rerank_enabled=eff_rerank_enabled,
            rerank_input_count=rerank_input_count,
            rerank_output_count=rerank_output_count,
            rerank_model_name=app_settings.qa_rerank_model_name,
            rerank_applied=rerank_applied,
            parent_recovered_chunks=0,
            parent_deduped_groups=0,
            normalized_query=normalized_query,
            rewritten_queries=query_variants,
            abstain_reason=("检索结果置信度不足" if low_confidence else "未检索到可用知识片段"),
            abstain_reason_code=(
                QAReasonCode.LOW_RETRIEVAL_CONFIDENCE.value if low_confidence else QAReasonCode.NO_RETRIEVAL_HIT.value
            ),
            trace_id=trace_id,
            request_id=request_id,
            task_type=task_type,
            planner_output=planned,
            selected_strategy=planned.get("selected_strategy"),
            workflow_steps_json=workflow_steps,
            tool_traces_json=tool_traces,
            session_context_json=session_context,
            final_answer_type=answer_src,
            selected_scope=selected_scope,
            selected_skill=selected_skill,
            planner_meta={
                **planned,
                "retrieval_rounds": retrieval_rounds,
                "fallback_triggered": fallback_triggered,
                "stop_reason": stop_reason,
                "source_count": source_count,
                "dominant_source_ratio": dominant_source_ratio,
                "multi_source_coverage": multi_source_coverage,
            },
            clarification_needed=False,
            workflow_summary="abstain_skill",
            source_count=source_count,
            dominant_source_ratio=dominant_source_ratio,
            multi_source_coverage=multi_source_coverage,
            fallback_triggered=fallback_triggered,
            retrieval_rounds=retrieval_rounds,
            stop_reason=stop_reason,
            query_understanding_summary=query_ux_summary,
            coverage_diagnostics=coverage_diagnostics_last,
        )
        return {
            "answer": answer,
            "references": [],
            "references_json": refs_payload,
            "evidence_bundles": None,
            "answer_source": answer_src,
            "used_files": [],
            "retrieval_meta": retrieval_meta,
        }
    except RuntimeError as exc:
        raise _qa_model_runtime_error("completion", exc) from exc


def persist_qa_citations(
    db: Session,
    *,
    message_id: int,
    references: list[dict] | None,
) -> None:
    """Insert normalized citation rows for a successful assistant message."""
    if not references:
        return
    for order, ref in enumerate(references):
        if not isinstance(ref, dict):
            continue
        try:
            file_id = int(ref["file_id"])
            chunk_id = int(ref["chunk_id"])
        except (KeyError, TypeError, ValueError):
            continue
        chunk_index = int(ref.get("chunk_index", 0))
        page = ref.get("page_number")
        page_number = int(page) if page is not None else None
        st = ref.get("section_title")
        section_title = (str(st)[:500] if st is not None else None)
        score_v = ref.get("score")
        try:
            score_f = float(score_v) if score_v is not None else None
        except (TypeError, ValueError):
            score_f = None
        db.add(
            QACitation(
                message_id=message_id,
                file_id=file_id,
                chunk_id=chunk_id,
                chunk_index=chunk_index,
                page_number=page_number,
                section_title=section_title,
                score=score_f,
                citation_order=order,
            )
        )
    db.commit()


def persist_retrieval_trace(
    db: Session,
    *,
    session_id: int,
    assistant_message_id: int | None,
    question: str,
    retrieval_meta: dict | None,
    answer_source: str | None,
    debug_json: dict | None = None,
) -> None:
    """Persist one retrieval trace row (success or failure)."""
    meta = retrieval_meta or {}
    dbg = debug_json if debug_json is not None else (dict(meta) if meta else None)
    trace_id = meta.get("trace_id") or uuid.uuid4().hex
    abstain_reason_code = normalize_reason_code(meta.get("abstain_reason_code") or meta.get("abstain_reason"))
    failure_reason_code = normalize_reason_code(
        meta.get("failure_reason_code")
        or (dbg.get("failure_reason_code") if isinstance(dbg, dict) else None)
    )
    is_abstained = bool(abstain_reason_code)
    failed = bool(
        failure_reason_code
        or (answer_source == "error")
        or (isinstance(dbg, dict) and (dbg.get("code") or dbg.get("message")))
    )
    trace = QARetrievalTrace(
        session_id=session_id,
        assistant_message_id=assistant_message_id,
        trace_id=trace_id,
        request_id=meta.get("request_id"),
        question=question,
        normalized_query=meta.get("normalized_query"),
        rewritten_queries_json=meta.get("rewritten_queries"),
        retrieval_mode=meta.get("retrieval_mode"),
        fusion_method=meta.get("fusion_method"),
        top_k=meta.get("top_k"),
        candidate_k=meta.get("candidate_k"),
        candidate_chunks=meta.get("candidate_chunks"),
        matched_chunks=meta.get("matched_chunks"),
        selected_chunks=meta.get("selected_chunks"),
        score_threshold_applied=meta.get("score_threshold_applied"),
        answer_source=answer_source or meta.get("answer_source"),
        retrieval_strategy=meta.get("retrieval_strategy"),
        filters_json=meta.get("filters"),
        selected_evidence_json=meta.get("selected_evidence"),
        evidence_bundles_json=meta.get("evidence_bundles"),
        strict_mode=meta.get("strict_mode"),
        is_abstained=is_abstained,
        failed=failed,
        abstain_reason=abstain_reason_code.value if abstain_reason_code else None,
        failure_reason=(
            failure_reason_code.value
            if failure_reason_code
            else (QAReasonCode.INTERNAL_ERROR.value if failed else None)
        ),
        model_name=meta.get("model_name"),
        token_usage_json=meta.get("token_usage"),
        latency_ms=meta.get("latency_ms"),
        latency_breakdown_json=meta.get("latency_breakdown"),
        task_type=meta.get("task_type"),
        tool_traces_json=meta.get("tool_traces_json"),
        workflow_steps_json=meta.get("workflow_steps_json"),
        session_context_json=meta.get("session_context_json"),
        rerank_enabled=meta.get("rerank_enabled"),
        rerank_applied=meta.get("rerank_applied"),
        rerank_model_name=meta.get("rerank_model_name"),
        debug_json=dbg,
    )
    db.add(trace)
    db.commit()
    if is_abstained or failed:
        reason_code = (
            (failure_reason_code.value if failure_reason_code else None)
            or (abstain_reason_code.value if abstain_reason_code else None)
            or QAReasonCode.INTERNAL_ERROR.value
        )
        sink_failure_case(
            build_failure_case(
                query=question,
                trace_id=trace_id,
                request_id=meta.get("request_id"),
                reason_code=reason_code,
                answer_summary=(answer_source or "unknown"),
                retrieved_refs=meta.get("selected_evidence"),
            )
        )
