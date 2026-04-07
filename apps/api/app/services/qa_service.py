from __future__ import annotations

import logging
import math
import re
import time
import uuid
from collections import defaultdict
from datetime import datetime

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.core.config import settings as app_settings
from app.models.file_record import FileRecord
from app.models.folder import Folder
from app.models.knowledge import KnowledgeChunk, QACitation, QAMessage, QARetrievalTrace, QASession
from app.models.system_setting import SystemSetting
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
from app.services.qa_guardrails import apply_evidence_guardrail, apply_input_guardrail, apply_output_guardrail
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
) -> dict:
    """Normalized retrieval_meta for API responses; keeps legacy min_score alongside min_similarity_score."""
    return {
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
        by_id[item["chunk"].id] = {
            "chunk": item["chunk"],
            "file_name": item["file_name"],
            "folder_id": item.get("folder_id"),
            "score": item["score"],
        }

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
            by_id[chunk.id] = {
                "chunk": chunk,
                "file_name": file_name,
                "folder_id": folder_id,
                "score": _score_neighbor_chunk(chunk, seeds),
            }

    seed_order = [item["chunk"].id for item in seeds]
    rest = [cid for cid in by_id if cid not in seed_ids]
    rest_sorted = sorted(
        rest,
        key=lambda cid: (by_id[cid]["chunk"].file_id, by_id[cid]["chunk"].chunk_index),
    )
    ordered_ids = seed_order + rest_sorted
    return [by_id[cid] for cid in ordered_ids if cid in by_id]


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
        it["_used_parent_for_pack"] = use_parent
    return out, parent_deduped_groups


def _pack_context_and_references(
    items: list[dict],
    *,
    seed_chunk_ids: set[int],
    max_context_chars: int,
    dedupe_adjacent_chunks: bool,
    redundancy_sim_threshold: float,
    redundancy_adjacent_window: int,
) -> tuple[list[str], list[dict], list[int], int, int, int, float]:
    """
    Greedy pack into max_context_chars. Prioritize seed hits (then by score, file, chunk_index).
    If item has _pack_text (parent recovery), use it for the LLM block body; references stay on child chunk.
    Returns context_blocks, references, used_files, context_chars, packed_chunks, parent_recovered_chunks.
    """
    if max_context_chars < 1:
        return [], [], [], 0, 0, 0, 0.0

    def sort_key(it: dict) -> tuple:
        cid = it["chunk"].id
        is_seed = 1 if cid in seed_chunk_ids else 0
        return (-is_seed, -it["score"], it["chunk"].file_id, it["chunk"].chunk_index)

    sorted_items = sorted(items, key=sort_key)
    context_blocks: list[str] = []
    references: list[dict] = []
    used_files: list[int] = []
    total_chars = 0
    last_content_norm: str | None = None
    parent_recovered_chunks = 0
    suppressed_redundant = 0
    considered = 0
    by_doc_kept: dict[int, list[tuple[int, str]]] = defaultdict(list)

    for item in sorted_items:
        considered += 1
        chunk = item["chunk"]
        body = item.get("_pack_text")
        if body is None:
            body = chunk.content
        block = f"[文件: {item['file_name']} | chunk: {chunk.chunk_index}]\n{body}"
        sep = "\n\n" if context_blocks else ""
        add_len = len(sep) + len(block)
        if total_chars + add_len > max_context_chars:
            break
        content_norm = body.strip()
        if dedupe_adjacent_chunks and last_content_norm is not None and content_norm == last_content_norm:
            suppressed_redundant += 1
            continue
        if dedupe_adjacent_chunks:
            same_doc = by_doc_kept.get(int(chunk.file_id), [])
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
            }
        )
        if chunk.file_id not in used_files:
            used_files.append(chunk.file_id)
        total_chars += add_len
        last_content_norm = content_norm
        by_doc_kept[int(chunk.file_id)].append((int(chunk.chunk_index), content_norm))

    redundancy_rate = suppressed_redundant / considered if considered else 0.0
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
            for query_embedding in query_embeddings:
                for item in _semantic_retrieval_pgvector(
                    db,
                    query_embedding=query_embedding,
                    compatible_file_ids=compatible_file_ids,
                    top_k=probe_limit,
                ):
                    cid = item["chunk"].id
                    if cid not in all_candidates or item["score"] > all_candidates[cid]["score"]:
                        all_candidates[cid] = item
            merged = list(all_candidates.values())
            merged.sort(key=lambda it: it["score"], reverse=True)
            if merged:
                return merged[:top_k], "pgvector_ann_hnsw"
        except Exception:
            logger.info("pgvector unavailable; switching to app-layer cosine fallback")

    # Fallback: app-layer cosine scan
    all_candidates: dict[int, dict] = {}
    for query_embedding in query_embeddings:
        for item in _semantic_retrieval_app_layer(
            db,
            query_embedding=query_embedding,
            compatible_file_ids=compatible_file_ids,
            top_k=max(top_k, int(app_settings.qa_pgvector_probe_limit)),
        ):
            cid = item["chunk"].id
            item["source"] = "semantic"
            if cid not in all_candidates or item["score"] > all_candidates[cid]["score"]:
                all_candidates[cid] = item
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
    for q in questions:
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
            if cid not in merged:
                merged[cid] = item
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
    """Rerank fused matches using a local cross-encoder.

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


def _build_context_from_matches(items: list[dict]) -> tuple[list[str], list[dict], list[int]]:
    context_blocks: list[str] = []
    references: list[dict] = []
    used_files: list[int] = []
    for item in items:
        chunk = item["chunk"]
        context_blocks.append(
            f"[文件: {item['file_name']} | chunk: {chunk.chunk_index}]\n{chunk.content}"
        )
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
    planned = plan_retrieval(
        task_type=task_type,
        normalized_query=normalized_query,
        rewritten_queries=_build_query_variants(question),
        scope_type=scope_type,
        strict_mode=strict_mode,
        top_k=top_k,
        candidate_k=candidate_k,
        file_ids=file_ids,
        selected_scope=selected_scope,
        selected_skill=selected_skill,
    )
    query_variants = planned.get("rewritten_queries") or [normalized_query]
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
    ]
    session_context = build_session_context(
        scope_type=scope_type,
        file_ids=file_ids,
        task_type=task_type,
        compare_targets=compare_targets,
        normalized_query=normalized_query,
        selected_scope=selected_scope,
        selected_skill=selected_skill,
        planner_summary={"strategy": planned.get("selected_strategy"), "queries": query_variants},
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
        raise QAServiceError("MODEL_REQUEST_FAILED", "模型服务请求失败，请检查当前配置与连接状态") from exc
    if not query_embeddings:
        raise QAServiceError("EMBEDDING_DATA_UNAVAILABLE", "查询向量为空，无法执行检索")

    compatible_file_ids = _collect_retrievable_file_ids(
        db,
        settings=settings,
        scope_type=scope_type,
        folder_id=folder_id,
        file_ids=file_ids,
        expected_dimension=len(query_embeddings[0]),
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
            raise QAServiceError("MODEL_REQUEST_FAILED", "模型服务请求失败，请检查当前配置与连接状态") from exc
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
            pack_items, parent_deduped_groups = _recover_parent_context_for_packing(db, deduped_items)
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
            )
            if packed_n < max(1, int(app_settings.qa_strict_min_citations)):
                logger.info("strict evidence decision=reject reason=insufficient_citations packed=%s", packed_n)
                raise QAServiceError(
                    "NO_RELIABLE_EVIDENCE",
                    "知识库证据不足，严格模式下无法给出可引用回答。",
                )
            evidence_guardrail = apply_evidence_guardrail(references)
            tool_traces.append(summarize_tool_trace("evidence_guardrail", evidence_guardrail))
            user_prompt = (
                "你是实验室内部知识库问答助手。你只允许根据下方「资料片段」回答问题。\n"
                "要求：\n"
                "- 结论必须可由资料支撑；不要引入资料未提及的关键事实。\n"
                "- 若单一来源证据已完整充分，可基于该来源作答；若多来源互补，请综合多来源关键信息。\n"
                "- 若资料不足以回答用户问题，请明确说明无法根据当前知识库资料作出完整回答，不要猜测，"
                "也不要改用通用知识或常识来替代知识库依据。\n\n"
                f"问题：{question}\n\n资料片段：\n"
                + "\n\n".join(context_blocks)
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
            pack_items, parent_deduped_groups = _recover_parent_context_for_packing(db, deduped_items)
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
            )
            evidence_guardrail = apply_evidence_guardrail(references)
            tool_traces.append(summarize_tool_trace("evidence_guardrail", evidence_guardrail))
            user_prompt = (
                (
                    "你是实验室知识库问答助手。请做多来源综合并保留引用意识。\n"
                    "要求：\n"
                    "- 先按主题归纳关键信息，再给总结。\n"
                    "- 关键结论必须由资料支撑；若证据冲突，要明确指出冲突。\n"
                    "- 若证据不足，明确说明局限并保守回答。\n\n"
                    f"问题：{question}\n\n资料片段：\n"
                    + "\n\n".join(context_blocks)
                )
                if task_type == TASK_MULTI_DOC_SYNTHESIS
                else (
                    "你是实验室知识库比较助手。请基于资料输出结构化比较。\n"
                    "输出格式：\n"
                    "1) 比较对象\n2) 共同点\n3) 差异点\n4) 冲突点/证据不足\n5) 结论\n"
                    "要求：仅依据资料，不要臆测。\n\n"
                    f"问题：{question}\n\n资料片段：\n"
                    + "\n\n".join(context_blocks)
                )
                if task_type == TASK_COMPARE
                else (
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
        raise QAServiceError("MODEL_REQUEST_FAILED", "模型服务请求失败，请检查当前配置与连接状态") from exc


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
