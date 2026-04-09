from __future__ import annotations

import re
from collections import Counter
from typing import Any

from app.services.context_packing import assess_coverage_shortfall, min_distinct_files_for_query_type


def apply_input_guardrail(question: str) -> dict[str, Any]:
    text = (question or "").lower()
    rule_map = {
        "policy_bypass_attempt": ["ignore system", "忽略系统", "绕过", "越权"],
        "unsupported_tool_request": ["联网搜索", "browser", "computer use", "调用工具", "tool call"],
        "agent_boundary_probe": ["/api/agent", "多agent", "handoff"],
    }
    matched_rules: list[str] = []
    for rule, tokens in rule_map.items():
        if any(token in text for token in tokens):
            matched_rules.append(rule)

    triggered = bool(matched_rules)
    return {
        "triggered": triggered,
        "severity": "high" if triggered else "none",
        "action": "constrain_to_text_kb" if triggered else "allow",
        "matched_rules": matched_rules,
    }


def apply_evidence_guardrail(references: list[dict] | None) -> dict[str, Any]:
    refs = references or []
    suspicious_refs: list[dict[str, Any]] = []
    for ref in refs:
        snippet = str(ref.get("snippet", "")).lower()
        signals = []
        if "ignore" in snippet and ("instruction" in snippet or "system" in snippet):
            signals.append("embedded_instruction_override")
        if "调用" in snippet and "工具" in snippet:
            signals.append("embedded_tool_invocation")
        if "do not follow" in snippet or "不要遵循" in snippet:
            signals.append("embedded_workflow_override")
        if signals:
            suspicious_refs.append(
                {
                    "file_id": ref.get("file_id"),
                    "chunk_id": ref.get("chunk_id"),
                    "signals": signals,
                }
            )
    return {
        "triggered": bool(suspicious_refs),
        "suspicious_chunks": len(suspicious_refs),
        "suspicious_references": suspicious_refs,
        "action": "treat_as_content_not_instruction" if suspicious_refs else "allow",
    }


def assess_evidence_sufficiency(
    *,
    references: list[dict] | None,
    reliable_match_count: int,
    top_reliable_score: float,
    score_floor: float,
    packed_reference_count: int,
    distinct_files_in_refs: int,
) -> dict[str, Any]:
    """
    粗粒度证据充分性（规则），用于答案层保守措辞；不替代 strict 模式硬阈值。
    """
    refs = references or []
    reasons: list[str] = []
    level = "strong"

    if refs and all(len(str(r.get("snippet", "") or "")) < 35 for r in refs):
        reasons.append("very_short_snippets")
        if level == "strong":
            level = "medium"

    if packed_reference_count <= 0:
        level = "weak"
        reasons.append("no_packed_references")
    elif packed_reference_count == 1:
        level = "medium"
        reasons.append("single_packed_reference")

    if reliable_match_count <= 1 and packed_reference_count <= 2:
        if level == "strong":
            level = "medium"
        reasons.append("few_retrieval_matches")

    if top_reliable_score < score_floor + 0.04:
        if level == "strong":
            level = "medium"
        if top_reliable_score < score_floor:
            level = "weak"
        reasons.append("low_top_reliable_score")

    if distinct_files_in_refs <= 1 and packed_reference_count >= 2:
        reasons.append("single_file_multiple_chunks")

    return {
        "level": level,
        "reasons": reasons,
        "reliable_match_count": reliable_match_count,
        "top_reliable_score": round(float(top_reliable_score), 4),
        "packed_reference_count": packed_reference_count,
        "distinct_files_in_refs": distinct_files_in_refs,
    }


def assess_coverage_sufficiency_for_answer(
    *,
    query_type: str,
    distinct_files_post_pack: int,
    dominant_file_ratio_post_pack: float,
    conflict_hint: dict[str, Any],
    coverage_diagnostics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """结合 query_type、最终文件覆盖、冲突信号与可选 diagnostics 的覆盖充分性（答案层）。"""
    min_req = min_distinct_files_for_query_type(query_type)
    base = assess_coverage_shortfall(
        query_type=query_type,
        distinct_files_post=int(distinct_files_post_pack),
        dominant_ratio_post=float(dominant_file_ratio_post_pack),
        min_required=min_req,
    )
    single_file_conflict = bool(conflict_hint.get("likely_conflict")) and int(distinct_files_post_pack) <= 1
    notices = list(base.get("notices") or [])
    if single_file_conflict:
        notices.append("检测到潜在冲突但引用仅来自单一文件，无法跨来源核对。")
    level = base.get("coverage_assessment", "coverage_good")
    if single_file_conflict and level == "coverage_good":
        level = "coverage_limited"
    weak_q = []
    if coverage_diagnostics:
        weak_q = list(coverage_diagnostics.get("weak_query_indices") or [])
    return {
        **base,
        "coverage_assessment": level,
        "coverage_shortfall": bool(base.get("coverage_shortfall")) or single_file_conflict,
        "single_file_conflict_risk": single_file_conflict,
        "weak_query_indices": weak_q,
        "notices": notices,
    }


def evidence_conflict_hint(references: list[dict] | None) -> dict[str, Any]:
    """极轻量冲突信号：跨文件且出现显式对立措辞时提示模型单列说明。"""
    refs = [r for r in (references or []) if isinstance(r, dict)]
    if len(refs) < 2:
        return {"likely_conflict": False, "reason": "insufficient_refs"}

    by_file: dict[int, list[str]] = {}
    for r in refs:
        try:
            fid = int(r.get("file_id", -1))
        except (TypeError, ValueError):
            continue
        if fid < 0:
            continue
        snip = str(r.get("snippet", "") or r.get("heading_path", "") or "")
        by_file.setdefault(fid, []).append(snip)

    if len(by_file) < 2:
        return {"likely_conflict": False, "reason": "single_file"}

    neg_pat = re.compile(r"(不(?:支持|能|可|要|应)|禁止|切勿|避免|不要|无需|无须|不存在|没有提供|未提供)")
    pos_pat = re.compile(r"(必须|务必|需要|应该|支持|可以|能够|推荐|建议|确保)")

    files_with_neg = sum(1 for ss in by_file.values() if neg_pat.search(" ".join(ss)))
    files_with_pos = sum(1 for ss in by_file.values() if pos_pat.search(" ".join(ss)))

    likely = files_with_neg >= 1 and files_with_pos >= 1 and len(by_file) >= 2
    return {
        "likely_conflict": bool(likely),
        "reason": "polarity_across_files" if likely else "no_heuristic_signal",
        "files_with_neg_modality": files_with_neg,
        "files_with_pos_modality": files_with_pos,
    }


def apply_output_guardrail(*, answer: str, references: list[dict] | None, compare_mode: bool) -> dict[str, Any]:
    refs = references or []
    warnings: list[str] = []
    if answer and not refs:
        warnings.append("answer_without_citations")

    file_counter = Counter(int(ref.get("file_id", -1)) for ref in refs if ref.get("file_id") is not None)
    dominant_ratio = 0.0
    if file_counter:
        dominant_ratio = max(file_counter.values()) / max(1, sum(file_counter.values()))
    if dominant_ratio >= 0.75 and len(file_counter) >= 1:
        warnings.append("single_source_dominance")
    if compare_mode and len(file_counter) <= 1:
        warnings.append("compare_evidence_asymmetric")

    return {
        "triggered": bool(warnings),
        "warnings": warnings,
        "dominant_source_ratio": round(dominant_ratio, 4),
        "source_count": len(file_counter),
        "action": "append_caution" if warnings else "allow",
    }
