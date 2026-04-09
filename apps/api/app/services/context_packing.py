"""
Coverage-aware pack 选择与诊断：多文件覆盖、parent/heading 边际收益、冗余惩罚、provenance 元数据。
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from app.core.config import settings as app_settings
from app.services.query_understanding import (
    QUERY_TYPE_COMPARE,
    QUERY_TYPE_FACTUAL,
    QUERY_TYPE_MULTI_HOP,
    QUERY_TYPE_OPEN_RISK,
    QUERY_TYPE_PROCEDURE,
    QUERY_TYPE_SUMMARY,
    QUERY_TYPE_TROUBLESHOOTING,
)

PROVENANCE_RETRIEVED_HIT = "retrieved_hit"
PROVENANCE_NEIGHBOR_EXPANSION = "neighbor_expansion"
PROVENANCE_PARENT_RECOVERY = "parent_recovery"
PROVENANCE_ADJACENT_PARENT = "adjacent_parent_expansion"
PROVENANCE_MAYBE_SUPPORTING = "maybe_supporting_context"

PACKING_STRATEGY_VERSION = "coverage_aware_v1"


def resolve_pack_provenance(item: dict[str, Any], seed_chunk_ids: set[int]) -> tuple[str, list[str], str]:
    """返回 (provenance_type, tags, context_chunk_role)。供 qa_service 引用块与单测复用。"""
    cid = int(item["chunk"].id)
    is_seed = cid in seed_chunk_ids
    used_parent = bool(item.get("_used_parent_for_pack"))
    adjacent = bool(item.get("_context_adjacent_expanded"))
    sr = str(item.get("source_reason") or "")
    tags: list[str] = []
    if adjacent:
        primary = PROVENANCE_ADJACENT_PARENT
        ctx_role = "adjacent_parent_context"
        tags.append(PROVENANCE_ADJACENT_PARENT)
        if used_parent:
            tags.append(PROVENANCE_PARENT_RECOVERY)
    elif used_parent and is_seed:
        primary = PROVENANCE_PARENT_RECOVERY
        ctx_role = "parent_body_for_hit_child"
        tags.append(PROVENANCE_PARENT_RECOVERY)
    elif (not is_seed) or sr == "neighbor_expansion":
        primary = PROVENANCE_NEIGHBOR_EXPANSION
        ctx_role = "neighbor_chunk_context"
        tags.append(PROVENANCE_NEIGHBOR_EXPANSION)
    else:
        primary = PROVENANCE_RETRIEVED_HIT
        ctx_role = "retrieval_hit_child"
        tags.append(PROVENANCE_RETRIEVED_HIT)
    return primary, tags, ctx_role


def _tokens(text: str) -> set[str]:
    compact = re.sub(r"\s+", " ", (text or "").strip().lower())
    return {tok for tok in re.split(r"[^\w\u4e00-\u9fff]+", compact) if tok}


def _jaccard(a: str, b: str) -> float:
    sa, sb = _tokens(a), _tokens(b)
    if not sa or not sb:
        return 0.0
    inter = len(sa & sb)
    union = len(sa | sb)
    return inter / union if union else 0.0


def min_distinct_files_for_query_type(query_type: str) -> int:
    m = {
        QUERY_TYPE_COMPARE: int(app_settings.qa_min_distinct_files_compare),
        QUERY_TYPE_SUMMARY: int(app_settings.qa_min_distinct_files_summary),
        QUERY_TYPE_MULTI_HOP: int(app_settings.qa_min_distinct_files_multi_hop),
        QUERY_TYPE_TROUBLESHOOTING: int(app_settings.qa_min_distinct_files_troubleshooting),
    }
    return max(1, m.get(query_type, 1))


def target_distinct_files_bias(query_type: str) -> int:
    """期望尽量覆盖的文件数（软目标，用于 seed 阶段）。"""
    base = min_distinct_files_for_query_type(query_type)
    if query_type in (QUERY_TYPE_COMPARE, QUERY_TYPE_SUMMARY, QUERY_TYPE_MULTI_HOP, QUERY_TYPE_TROUBLESHOOTING):
        return max(base, 2)
    if query_type == QUERY_TYPE_PROCEDURE:
        return 1
    return max(1, min(2, base))


def compute_match_list_coverage_stats(items: list[dict], *, label: str) -> dict[str, Any]:
    if not items:
        return {
            "label": label,
            "candidate_chunk_count": 0,
            "candidate_parent_count": 0,
            "candidate_file_count": 0,
            "top_k_file_distribution": {},
            "dominant_file_ratio_pre_pack": 0.0,
            "distinct_files_pre_pack": 0,
            "distinct_parents_pre_pack": 0,
        }
    by_file: dict[int, int] = defaultdict(int)
    parents: set[tuple[int, int | None]] = set()
    for it in items:
        ch = it["chunk"]
        fid = int(ch.file_id)
        by_file[fid] += 1
        pid = getattr(ch, "parent_chunk_id", None)
        parents.add((fid, int(pid) if pid is not None else None))
    total = len(items)
    dom = max(by_file.values()) / total if total else 0.0
    dist = {str(k): v for k, v in sorted(by_file.items(), key=lambda x: -x[1])[:12]}
    return {
        "label": label,
        "candidate_chunk_count": total,
        "candidate_parent_count": len(parents),
        "candidate_file_count": len(by_file),
        "top_k_file_distribution": dist,
        "dominant_file_ratio_pre_pack": round(dom, 4),
        "distinct_files_pre_pack": len(by_file),
        "distinct_parents_pre_pack": len(parents),
    }


def compute_coverage_by_query(
    reliable_matches: list[dict],
    *,
    retrieval_queries: list[str],
) -> dict[str, Any]:
    """按 matched_query_index 聚合（若缺失则记为 -1）。"""
    nq = len(retrieval_queries)
    by_q: dict[int, dict[str, int]] = {
        i: {"candidates": 0, "distinct_files": 0, "final_kept": 0} for i in range(nq)
    }
    by_q[-1] = {"candidates": 0, "distinct_files": 0, "final_kept": 0}
    for it in reliable_matches:
        qi = int(it.get("matched_query_index", -1))
        if qi not in by_q:
            by_q[qi] = {"candidates": 0, "distinct_files": 0, "final_kept": 0}
        by_q[qi]["candidates"] += 1
    for qi, bucket in by_q.items():
        files = {
            int(it["chunk"].file_id)
            for it in reliable_matches
            if int(it.get("matched_query_index", -1)) == qi
        }
        bucket["distinct_files"] = len(files)
    out: dict[str, Any] = {"queries": retrieval_queries, "by_index": {}}
    for qi in sorted(by_q.keys()):
        b = by_q[qi]
        qtext = retrieval_queries[qi] if 0 <= qi < len(retrieval_queries) else ("(unknown_query_index)" if qi >= 0 else "(unset_index)")
        out["by_index"][str(qi)] = {"query": qtext, **b}
    unmatched_queries = [str(i) for i in range(nq) if by_q.get(i, {}).get("candidates", 0) == 0]
    weak_queries = [str(i) for i in range(nq) if 0 < by_q.get(i, {}).get("candidates", 0) <= 1]
    return {
        "coverage_by_query": out,
        "weak_query_indices": weak_queries,
        "unmatched_queries": unmatched_queries,
    }


def merge_coverage_by_query_final(
    coverage_by_query_block: dict[str, Any],
    *,
    final_refs: list[dict],
) -> dict[str, Any]:
    """在最终引用条目中统计每个 query index 保留数量。"""
    out = dict(coverage_by_query_block)
    inner = out.get("coverage_by_query") or {}
    by_index = dict(inner.get("by_index") or {})
    counts: dict[str, int] = defaultdict(int)
    for ref in final_refs:
        if not isinstance(ref, dict):
            continue
        raw = ref.get("matched_query_index", -1)
        try:
            qi = int(raw) if raw is not None else -1
        except (TypeError, ValueError):
            qi = -1
        counts[str(qi)] += 1
    for k, row in by_index.items():
        row = dict(row)
        row["final_kept"] = int(counts.get(k, 0))
        by_index[k] = row
    inner = {**inner, "by_index": by_index}
    out["coverage_by_query"] = inner
    return out


def compute_post_pack_context_stats(
    references: list[dict],
    *,
    chars_per_file: dict[int, int],
) -> dict[str, Any]:
    """基于最终引用与 packing 时的每文件字符统计（垄断率优先用字符占比）。"""
    empty = {
        "final_context_chunk_count": 0,
        "final_context_parent_count": 0,
        "final_context_file_count": 0,
        "distinct_files_post_pack": 0,
        "distinct_parents_post_pack": 0,
        "dominant_file_ratio_post_pack": 0.0,
        "dominant_file_ratio_chunks": 0.0,
        "selected_file_distribution": {},
        "selected_parent_distribution": {},
        "chars_per_file": {},
        "parents_per_file": {},
        "chunks_per_file": {},
    }
    if not references:
        return empty
    by_file: dict[int, int] = defaultdict(int)
    parents: set[tuple[int, int | None]] = set()
    parents_per_file: dict[int, set[int | None]] = defaultdict(set)
    for ref in references:
        if not isinstance(ref, dict):
            continue
        try:
            fid = int(ref.get("file_id", 0))
        except (TypeError, ValueError):
            continue
        if fid <= 0:
            continue
        by_file[fid] += 1
        pid = ref.get("parent_chunk_id")
        pk = int(pid) if pid is not None else None
        parents.add((fid, pk))
        parents_per_file[fid].add(pk)
    total_chunks = sum(by_file.values())
    dom_chunks = max(by_file.values()) / total_chunks if total_chunks else 0.0
    dist = {str(k): v for k, v in sorted(by_file.items(), key=lambda x: -x[1])[:16]}
    sparent = {str(k): len(v) for k, v in sorted(parents_per_file.items())}
    cchars = {str(k): v for k, v in sorted(chars_per_file.items())}
    # dominant_file_ratio_post_pack：主指标 = 各文件进入 LLM 上下文的字符占比（反映「单文献垄断」）
    # dominant_file_ratio_chunks：辅助 = 引用条数占比
    total_chars = sum(chars_per_file.values())
    if total_chars > 0 and chars_per_file:
        dom_chars = max(chars_per_file.values()) / total_chars
    else:
        dom_chars = dom_chunks
    return {
        "final_context_chunk_count": total_chunks,
        "final_context_parent_count": len(parents),
        "final_context_file_count": len(by_file),
        "distinct_files_post_pack": len(by_file),
        "distinct_parents_post_pack": len(parents),
        "dominant_file_ratio_post_pack": round(dom_chars, 4),
        "dominant_file_ratio_chunks": round(dom_chunks, 4),
        "selected_file_distribution": dist,
        "selected_parent_distribution": sparent,
        "chars_per_file": cchars,
        "parents_per_file": {str(k): len(v) for k, v in parents_per_file.items()},
        "chunks_per_file": dist,
    }


def rank_files_by_context_chars(chars_per_file: dict[int, int]) -> list[int]:
    return sorted(chars_per_file.keys(), key=lambda fid: (-chars_per_file[fid], fid))


def build_coverage_diagnostics_payload(
    *,
    pre_pack_items: list[dict],
    references: list[dict],
    retrieval_queries: list[str],
    reliable_matches: list[dict],
    query_type: str,
    coverage_select_trace: dict[str, Any] | None,
    packing_trace: dict[str, Any] | None,
    compare_side_hint: dict[str, Any] | None = None,
) -> dict[str, Any]:
    pre = compute_match_list_coverage_stats(pre_pack_items, label="pre_pack_candidates")
    del pre["label"]
    by_q = compute_coverage_by_query(reliable_matches, retrieval_queries=retrieval_queries)
    by_q = merge_coverage_by_query_final(by_q, final_refs=references)
    chars_pf: dict[int, int] = {}
    if packing_trace and isinstance(packing_trace.get("per_file_context_chars"), dict):
        for k, v in packing_trace["per_file_context_chars"].items():
            try:
                chars_pf[int(k)] = int(v)
            except (TypeError, ValueError):
                continue
    post = compute_post_pack_context_stats(references, chars_per_file=chars_pf)
    min_r = min_distinct_files_for_query_type(query_type)
    shortfall = assess_coverage_shortfall(
        query_type=query_type,
        distinct_files_post=int(post["distinct_files_post_pack"]),
        dominant_ratio_post=float(post["dominant_file_ratio_post_pack"]),
        min_required=min_r,
    )
    file_ranks = rank_files_by_context_chars(chars_pf)
    source_rank_map = {fid: i + 1 for i, fid in enumerate(file_ranks)}
    compact_trace: dict[str, Any] = {
        "packing_strategy_version": (coverage_select_trace or {}).get("packing_strategy_version")
        or PACKING_STRATEGY_VERSION,
        "coverage_constraints_applied": (coverage_select_trace or {}).get("coverage_constraints_applied") or [],
        "coverage_shortfall_notice": shortfall.get("notices") or [],
        "skipped_due_to_file_cap": (packing_trace or {}).get("suppressed_file_budget", 0),
        "skipped_due_to_parent_cap": (coverage_select_trace or {}).get("skipped_due_to_parent_cap", 0),
        "skipped_due_to_similarity": (coverage_select_trace or {}).get("skipped_due_to_similarity", 0)
        + (packing_trace or {}).get("suppressed_redundant_adjacent", 0)
        + (packing_trace or {}).get("suppressed_parent_similarity", 0),
        "skipped_due_to_budget": (packing_trace or {}).get("considered_items", 0)
        - (packing_trace or {}).get("packed_blocks", 0)
        if packing_trace
        else 0,
    }
    if compare_side_hint:
        compact_trace["compare_side_coverage_hint"] = compare_side_hint
    detail: dict[str, Any] | None = None
    if bool(app_settings.qa_packing_trace_enabled):
        detail = {
            "coverage_select": coverage_select_trace or {},
            "packing": packing_trace or {},
        }
    return {
        "query_type": query_type,
        **pre,
        **post,
        **by_q,
        "coverage_shortfall": shortfall,
        "dominant_source_warning": bool(shortfall.get("dominant_source_warning")),
        "citation_source_count": len(references),
        "source_file_rank_by_context_chars": {str(k): source_rank_map.get(k) for k in sorted(source_rank_map.keys())},
        "packing_decision_trace": compact_trace,
        "packing_decision_trace_detail": detail,
    }


def _heading_key(chunk: Any) -> str:
    meta = chunk.metadata_json if isinstance(chunk.metadata_json, dict) else {}
    hp = meta.get("heading_path")
    return str(hp).strip() if hp is not None else ""


def _rel_score(it: dict) -> float:
    return float(it.get("rerank_score", it.get("score", 0.0)))


def _parent_key(it: dict) -> tuple[int, int | None]:
    ch = it["chunk"]
    pid = getattr(ch, "parent_chunk_id", None)
    return (int(ch.file_id), int(pid) if pid is not None else None)


def _primary_text(it: dict) -> str:
    t = it.get("_pack_text_primary") or it.get("_pack_text") or (it["chunk"].content or "")
    return str(t).strip()


def select_pack_items_coverage_two_phase(
    items: list[dict],
    *,
    query_type: str,
    seed_chunk_ids: set[int],
    max_total: int,
) -> tuple[list[dict], dict[str, Any]]:
    """
    阶段1：优先从不同 file 各取一条高分命中，扩大覆盖。
    阶段2：边际收益填充（新文件 / 新 heading 奖励，相似度与单文件占比惩罚）。
    """
    trace: dict[str, Any] = {
        "packing_strategy_version": PACKING_STRATEGY_VERSION,
        "skipped_due_to_file_cap": 0,
        "skipped_due_to_parent_cap": 0,
        "skipped_due_to_similarity": 0,
        "skipped_due_to_budget": 0,
        "coverage_constraints_applied": [],
    }
    _ = seed_chunk_ids  # 保留签名供调用方扩展（如同 file 内 seed 优先）
    if not items:
        return [], trace

    max_pf = max(1, int(app_settings.qa_coverage_max_parents_per_file))
    max_total = max(1, max_total)
    target_files = target_distinct_files_bias(query_type)
    trace["coverage_constraints_applied"] = [
        f"coverage_max_parents_per_file={max_pf}",
        f"max_total={max_total}",
        f"target_distinct_files={target_files}",
    ]

    pool = sorted(items, key=_rel_score, reverse=True)
    selected: list[dict] = []
    seen_chunk: set[int] = set()
    per_file_parent_keys: dict[int, set[tuple[int, int | None]]] = defaultdict(set)

    def parent_cap_ok(it: dict) -> bool:
        fid = int(it["chunk"].file_id)
        pk = _parent_key(it)
        if pk[1] is None:
            # 无 parent：每文件允许多个独立 child，占用一个「虚拟 parent 槽」
            if pk in per_file_parent_keys[fid]:
                return True
            return len(per_file_parent_keys[fid]) < max_pf
        if pk in per_file_parent_keys[fid]:
            return True
        return len(per_file_parent_keys[fid]) < max_pf

    def register(it: dict) -> None:
        fid = int(it["chunk"].file_id)
        per_file_parent_keys[fid].add(_parent_key(it))

    # --- Phase 1: 新文件优先 ---
    files_with_seed: set[int] = set()
    idx = 0
    while idx < len(pool) and len(selected) < max_total and len(files_with_seed) < target_files:
        picked = None
        pick_j = -1
        for j, it in enumerate(pool):
            cid = int(it["chunk"].id)
            if cid in seen_chunk:
                continue
            fid = int(it["chunk"].file_id)
            if fid in files_with_seed:
                continue
            if not parent_cap_ok(it):
                trace["skipped_due_to_parent_cap"] += 1
                continue
            picked = it
            pick_j = j
            break
        if picked is None:
            break
        pool.pop(pick_j)
        selected.append(picked)
        seen_chunk.add(int(picked["chunk"].id))
        register(picked)
        files_with_seed.add(int(picked["chunk"].file_id))
        idx += 1

    # 高分补位至至少 min(len(items), target_files) 条或继续填满
    for it in sorted(pool, key=_rel_score, reverse=True):
        if len(selected) >= max_total:
            break
        cid = int(it["chunk"].id)
        if cid in seen_chunk:
            continue
        if not parent_cap_ok(it):
            trace["skipped_due_to_parent_cap"] += 1
            continue
        selected.append(it)
        seen_chunk.add(cid)
        register(it)

    pool = [it for it in items if int(it["chunk"].id) not in seen_chunk]
    pool.sort(key=_rel_score, reverse=True)

    selected_texts = [_primary_text(x) for x in selected]
    selected_files = {int(x["chunk"].file_id) for x in selected}
    selected_headings: set[tuple[int, str]] = {
        (int(x["chunk"].file_id), _heading_key(x["chunk"])) for x in selected
    }

    dom_ratio_limit = float(app_settings.qa_max_dominant_file_ratio)
    j_thr = float(app_settings.qa_redundancy_jaccard_threshold_coverage)

    while pool and len(selected) < max_total:
        char_counts: dict[int, int] = defaultdict(int)
        for x in selected:
            char_counts[int(x["chunk"].file_id)] += len(_primary_text(x))

        best_it = None
        best_gain = -1e9
        for it in list(pool):
            cid = int(it["chunk"].id)
            if cid in seen_chunk:
                continue
            if not parent_cap_ok(it):
                trace["skipped_due_to_parent_cap"] += 1
                continue
            fid = int(it["chunk"].file_id)
            rel = _rel_score(it)
            txt = _primary_text(it)
            sim_pen = 0.0
            if app_settings.qa_enable_redundancy_penalty_coverage:
                for prev in selected_texts:
                    if _jaccard(txt, prev) >= j_thr:
                        sim_pen = 0.35
                        break
            if sim_pen > 0:
                trace["skipped_due_to_similarity"] += 1

            new_file = 1.0 if fid not in selected_files else 0.0
            hk = (fid, _heading_key(it["chunk"]))
            nh = _heading_key(it["chunk"])
            new_h = 1.0 if nh and hk not in selected_headings else 0.0
            heading_bonus = 0.08 * new_h if app_settings.qa_enable_heading_diversity_bonus else 0.0
            file_bonus = 0.12 * new_file
            if query_type in (QUERY_TYPE_COMPARE, QUERY_TYPE_SUMMARY, QUERY_TYPE_MULTI_HOP, QUERY_TYPE_TROUBLESHOOTING):
                file_bonus *= 1.35
                heading_bonus *= 1.15

            dom_pen = 0.0
            if app_settings.qa_enable_dominant_source_penalty:
                fc = char_counts[fid] + len(txt)
                total_c = sum(char_counts.values()) + len(txt)
                ratio = fc / max(1, total_c)
                if ratio > dom_ratio_limit and new_file < 0.5:
                    dom_pen = 0.18 * (ratio - dom_ratio_limit)

            gain = rel + file_bonus + heading_bonus - sim_pen - dom_pen
            if gain > best_gain:
                best_gain = gain
                best_it = it

        if best_it is None:
            break
        pool.remove(best_it)
        selected.append(best_it)
        seen_chunk.add(int(best_it["chunk"].id))
        register(best_it)
        selected_files.add(int(best_it["chunk"].file_id))
        selected_headings.add((int(best_it["chunk"].file_id), _heading_key(best_it["chunk"])))
        selected_texts.append(_primary_text(best_it))

    trace["output_count"] = len(selected)
    trace["distinct_files_after_select"] = len({int(x["chunk"].file_id) for x in selected})
    return selected, trace


def build_provenance_tags(
    *,
    chunk_id: int,
    seed_chunk_ids: set[int],
    used_parent: bool,
    adjacent: bool,
) -> tuple[str, list[str]]:
    tags: list[str] = []
    is_seed = chunk_id in seed_chunk_ids
    if not is_seed:
        tags.append(PROVENANCE_NEIGHBOR_EXPANSION)
        primary = PROVENANCE_NEIGHBOR_EXPANSION
    else:
        tags.append(PROVENANCE_RETRIEVED_HIT)
        primary = PROVENANCE_RETRIEVED_HIT
    if used_parent:
        tags.append(PROVENANCE_PARENT_RECOVERY)
        if is_seed:
            primary = PROVENANCE_PARENT_RECOVERY
    if adjacent:
        tags.append(PROVENANCE_ADJACENT_PARENT)
    return primary, tags


def assess_coverage_shortfall(
    *,
    query_type: str,
    distinct_files_post: int,
    dominant_ratio_post: float,
    min_required: int,
) -> dict[str, Any]:
    requires_multi = query_type in (
        QUERY_TYPE_COMPARE,
        QUERY_TYPE_SUMMARY,
        QUERY_TYPE_MULTI_HOP,
        QUERY_TYPE_TROUBLESHOOTING,
    )
    missing = requires_multi and distinct_files_post < min_required
    poor = distinct_files_post < 1 or dominant_ratio_post > float(app_settings.qa_max_dominant_file_ratio) + 0.1
    if missing or poor:
        level = "coverage_poor" if missing else "coverage_limited"
    elif dominant_ratio_post > 0.55:
        level = "coverage_limited"
    else:
        level = "coverage_good"
    notices: list[str] = []
    if missing:
        notices.append(
            f"期望至少 {min_required} 个来源文件，实际仅 {distinct_files_post} 个；比较/综合结论需谨慎。"
        )
    if dominant_ratio_post > float(app_settings.qa_max_dominant_file_ratio):
        notices.append(
            f"单文件字符占比过高（>{app_settings.qa_max_dominant_file_ratio:.0%}），存在单文献主导风险。"
        )
    return {
        "coverage_assessment": level,
        "coverage_shortfall": missing or poor,
        "requires_multi_source_but_missing": missing,
        "dominant_source_warning": dominant_ratio_post > float(app_settings.qa_max_dominant_file_ratio),
        "notices": notices,
        "min_distinct_files_required": min_required if requires_multi else 1,
        "distinct_files_observed": distinct_files_post,
        "dominant_file_ratio_post_pack": round(dominant_ratio_post, 4),
    }
