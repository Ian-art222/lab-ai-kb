from __future__ import annotations

import re
from typing import Any


TASK_SIMPLE_QA = "simple_qa"
TASK_MULTI_DOC_SYNTHESIS = "multi_doc_synthesis"
TASK_COMPARE = "compare"
TASK_COLLECTION_SCOPED_QA = "collection_scoped_qa"
TASK_ABSTAIN = "abstain_or_insufficient_context"


def normalize_query_text(question: str) -> str:
    return " ".join((question or "").split()).strip()


def classify_task_type(
    *,
    question: str,
    scope_type: str,
    file_ids: list[int] | None,
) -> dict[str, Any]:
    normalized = normalize_query_text(question).lower()
    compare_patterns = [
        "比较",
        "区别",
        "异同",
        "不同点",
        "相同点",
        "compare",
        "difference",
        "versus",
        "vs",
    ]
    synthesis_patterns = [
        "综述",
        "总结多个",
        "跨文档",
        "多篇",
        "多个文件",
        "多来源",
        "synthesis",
        "overview",
        "survey",
    ]
    insufficient_patterns = [
        "不知道",
        "无法判断",
        "insufficient",
        "不确定",
    ]
    if any(token in normalized for token in compare_patterns):
        return {"task_type": TASK_COMPARE, "reason": "matched_compare_keywords"}
    if scope_type in {"files", "folder"}:
        return {"task_type": TASK_COLLECTION_SCOPED_QA, "reason": "scoped_question"}
    if any(token in normalized for token in synthesis_patterns):
        return {"task_type": TASK_MULTI_DOC_SYNTHESIS, "reason": "matched_synthesis_keywords"}
    if any(token in normalized for token in insufficient_patterns) and not file_ids:
        return {"task_type": TASK_ABSTAIN, "reason": "insufficient_context_signal"}
    return {"task_type": TASK_SIMPLE_QA, "reason": "default_simple"}


def extract_compare_targets(question: str) -> list[str]:
    normalized = normalize_query_text(question)
    m = re.search(r"比较(.+?)和(.+?)(的|在|$)", normalized)
    if m:
        return [m.group(1).strip(), m.group(2).strip()]
    m2 = re.search(r"(.+?)\s+(?:vs|VS|versus)\s+(.+)", normalized)
    if m2:
        return [m2.group(1).strip(), m2.group(2).strip()]
    return []


def plan_retrieval(
    *,
    task_type: str,
    normalized_query: str,
    rewritten_queries: list[str],
    scope_type: str,
    strict_mode: bool,
    top_k: int,
    candidate_k: int,
    file_ids: list[int] | None,
) -> dict[str, Any]:
    base_queries = [q for q in rewritten_queries if q.strip()]
    if normalized_query and normalized_query not in base_queries:
        base_queries.insert(0, normalized_query)
    max_queries = 2
    selected_strategy = "light_qa"
    planned_top_k = top_k
    planned_candidate_k = candidate_k
    prefer_diversity = False
    workflow_steps = [
        {"step": "classify_task_type", "status": "completed"},
        {"step": "plan_retrieval", "status": "completed"},
    ]

    if task_type == TASK_MULTI_DOC_SYNTHESIS:
        max_queries = 3
        selected_strategy = "multi_source_synthesis"
        planned_top_k = max(top_k, 6)
        planned_candidate_k = max(candidate_k, planned_top_k * 2)
        prefer_diversity = True
    elif task_type == TASK_COMPARE:
        max_queries = 3
        selected_strategy = "compare_dual_focus"
        planned_top_k = max(top_k, 6)
        planned_candidate_k = max(candidate_k, planned_top_k * 2)
        prefer_diversity = True
        workflow_steps.append({"step": "compare_evidence_sets", "status": "pending"})
    elif task_type == TASK_COLLECTION_SCOPED_QA:
        selected_strategy = "scope_focused_qa"
        planned_top_k = max(top_k, 4)
    elif task_type == TASK_ABSTAIN:
        selected_strategy = "conservative_abstain"

    scopes = {
        "scope_type": scope_type,
        "file_ids": file_ids or [],
        "strict_mode": strict_mode,
    }
    return {
        "task_type": task_type,
        "normalized_query": normalized_query,
        "rewritten_queries": base_queries[:max_queries],
        "selected_strategy": selected_strategy,
        "top_k": planned_top_k,
        "candidate_k": planned_candidate_k,
        "prefer_diversity": prefer_diversity,
        "scopes": scopes,
        "workflow_steps": workflow_steps,
    }


def build_session_context(
    *,
    scope_type: str,
    file_ids: list[int] | None,
    task_type: str,
    compare_targets: list[str] | None,
    normalized_query: str,
) -> dict[str, Any]:
    return {
        "scope_type": scope_type,
        "file_ids": file_ids or [],
        "task_type": task_type,
        "compare_targets": compare_targets or [],
        "recent_query_summary": normalized_query[:200],
    }


def summarize_tool_trace(tool_name: str, data: dict[str, Any]) -> dict[str, Any]:
    return {"tool": tool_name, "summary": data}
