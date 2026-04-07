from __future__ import annotations

import re
from typing import Any

TASK_SIMPLE_QA = "simple_qa"
TASK_MULTI_DOC_SYNTHESIS = "multi_doc_synthesis"
TASK_COMPARE = "compare"
TASK_COLLECTION_SCOPED_QA = "collection_scoped_qa"
TASK_CLARIFICATION_NEEDED = "clarification_needed"
TASK_ABSTAIN = "abstain_or_insufficient_context"

SCOPE_EXPLICIT_FILE = "explicit_file_scope"
SCOPE_COLLECTION = "collection_scope"
SCOPE_DEFAULT = "default_kb_scope"
SCOPE_DIAGNOSTICS_AWARE = "diagnostics_aware_scope"

SKILL_QA = "qa_skill"
SKILL_SYNTHESIS = "synthesis_skill"
SKILL_COMPARE = "compare_skill"
SKILL_SCOPED_QA = "scoped_qa_skill"
SKILL_CLARIFY = "clarify_skill"
SKILL_ABSTAIN = "abstain_skill"


def normalize_query_text(question: str) -> str:
    return " ".join((question or "").split()).strip()


def _route_scope(scope_type: str, question: str, file_ids: list[int] | None) -> dict[str, str]:
    normalized = normalize_query_text(question).lower()
    if any(token in normalized for token in ["trace", "diagnostics", "排障", "诊断", "reason code"]):
        return {"selected_scope": SCOPE_DIAGNOSTICS_AWARE, "scope_reason": "diagnostics_intent"}
    if file_ids:
        return {"selected_scope": SCOPE_EXPLICIT_FILE, "scope_reason": "explicit_file_ids"}
    if scope_type in {"files", "folder"}:
        return {"selected_scope": SCOPE_COLLECTION, "scope_reason": "collection_scope_param"}
    return {"selected_scope": SCOPE_DEFAULT, "scope_reason": "default_scope"}


def classify_task_type(
    *,
    question: str,
    scope_type: str,
    file_ids: list[int] | None,
) -> dict[str, Any]:
    """Back-compatible task classifier used by legacy tests/callers."""
    routed = route_task_scope_skill(question=question, scope_type=scope_type, file_ids=file_ids)
    return {
        "task_type": routed["task_type"],
        "reason": routed["task_reason"],
        "selected_scope": routed["selected_scope"],
        "selected_skill": routed["selected_skill"],
    }


def route_task_scope_skill(*, question: str, scope_type: str, file_ids: list[int] | None) -> dict[str, Any]:
    normalized = normalize_query_text(question).lower()
    compare_patterns = ["比较", "区别", "异同", "compare", "difference", "versus", " vs "]
    synthesis_patterns = ["综述", "跨文档", "多篇", "多来源", "synthesis", "survey", "overview"]
    clarify_patterns = ["哪个", "哪一个", "不明确", "先澄清", "clarify"]
    abstain_patterns = ["不知道", "无法判断", "insufficient", "不确定", "随便说说"]

    scope = _route_scope(scope_type, question, file_ids)
    selected_scope = scope["selected_scope"]

    compare_targets = extract_compare_targets(question)
    if any(token in normalized for token in compare_patterns):
        if len(compare_targets) < 2:
            return {
                "task_type": TASK_CLARIFICATION_NEEDED,
                "task_reason": "compare_targets_missing",
                "selected_scope": selected_scope,
                "scope_reason": scope["scope_reason"],
                "selected_skill": SKILL_CLARIFY,
                "clarification_needed": True,
                "compare_targets": compare_targets,
            }
        return {
            "task_type": TASK_COMPARE,
            "task_reason": "matched_compare_keywords",
            "selected_scope": selected_scope,
            "scope_reason": scope["scope_reason"],
            "selected_skill": SKILL_COMPARE,
            "clarification_needed": False,
            "compare_targets": compare_targets,
        }

    if selected_scope in {SCOPE_EXPLICIT_FILE, SCOPE_COLLECTION}:
        return {
            "task_type": TASK_COLLECTION_SCOPED_QA,
            "task_reason": "scoped_question",
            "selected_scope": selected_scope,
            "scope_reason": scope["scope_reason"],
            "selected_skill": SKILL_SCOPED_QA,
            "clarification_needed": False,
            "compare_targets": [],
        }

    if any(token in normalized for token in synthesis_patterns):
        return {
            "task_type": TASK_MULTI_DOC_SYNTHESIS,
            "task_reason": "matched_synthesis_keywords",
            "selected_scope": selected_scope,
            "scope_reason": scope["scope_reason"],
            "selected_skill": SKILL_SYNTHESIS,
            "clarification_needed": False,
            "compare_targets": [],
        }

    if selected_scope == SCOPE_DIAGNOSTICS_AWARE:
        return {
            "task_type": TASK_ABSTAIN,
            "task_reason": "diagnostics_scope_conservative",
            "selected_scope": selected_scope,
            "scope_reason": scope["scope_reason"],
            "selected_skill": SKILL_ABSTAIN,
            "clarification_needed": False,
            "compare_targets": [],
        }

    if any(token in normalized for token in clarify_patterns) and len(normalized) <= 12:
        return {
            "task_type": TASK_CLARIFICATION_NEEDED,
            "task_reason": "query_too_ambiguous",
            "selected_scope": selected_scope,
            "scope_reason": scope["scope_reason"],
            "selected_skill": SKILL_CLARIFY,
            "clarification_needed": True,
            "compare_targets": [],
        }

    if any(token in normalized for token in abstain_patterns) and not file_ids:
        return {
            "task_type": TASK_ABSTAIN,
            "task_reason": "insufficient_context_signal",
            "selected_scope": selected_scope,
            "scope_reason": scope["scope_reason"],
            "selected_skill": SKILL_ABSTAIN,
            "clarification_needed": False,
            "compare_targets": [],
        }

    return {
        "task_type": TASK_SIMPLE_QA,
        "task_reason": "default_simple",
        "selected_scope": selected_scope,
        "scope_reason": scope["scope_reason"],
        "selected_skill": SKILL_QA,
        "clarification_needed": False,
        "compare_targets": [],
    }


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
    selected_scope: str | None = None,
    selected_skill: str | None = None,
) -> dict[str, Any]:
    base_queries = [q for q in rewritten_queries if q.strip()]
    if normalized_query and normalized_query not in base_queries:
        base_queries.insert(0, normalized_query)

    selected_strategy = "single_pass_qa"
    planned_top_k = top_k
    planned_candidate_k = candidate_k
    prefer_diversity = False
    max_queries = min(4, max(2, len(base_queries) or 2))

    if task_type == TASK_MULTI_DOC_SYNTHESIS:
        selected_strategy = "coverage_oriented_synthesis"
        planned_top_k = max(top_k, 6)
        planned_candidate_k = max(candidate_k, planned_top_k * 2)
        prefer_diversity = True
    elif task_type == TASK_COMPARE:
        selected_strategy = "side_by_side_compare_retrieval"
        planned_top_k = max(top_k, 6)
        planned_candidate_k = max(candidate_k, planned_top_k * 2)
        prefer_diversity = True
    elif task_type == TASK_COLLECTION_SCOPED_QA:
        selected_strategy = "scoped_retrieval"
        planned_top_k = max(top_k, 4)
    elif task_type == TASK_CLARIFICATION_NEEDED:
        selected_strategy = "clarify_before_retrieval"
        planned_top_k = max(1, min(top_k, 3))
    elif task_type == TASK_ABSTAIN:
        selected_strategy = "conservative_abstain"

    stop_conditions = [
        "enough_evidence",
        "max_rounds_reached",
        "insufficient_after_fallback",
        "clarification_required",
    ]

    query_plan = [
        {
            "round": 1,
            "queries": base_queries[:max_queries],
            "top_k": planned_top_k,
            "candidate_k": planned_candidate_k,
            "goal": "primary_retrieval",
        }
    ]
    if task_type not in {TASK_ABSTAIN, TASK_CLARIFICATION_NEEDED}:
        fallback_queries = []
        for q in base_queries[:max_queries]:
            stripped = re.sub(r"[^\w\u4e00-\u9fff]+", " ", q).strip()
            if stripped and stripped not in fallback_queries:
                fallback_queries.append(stripped)
        query_plan.append(
            {
                "round": 2,
                "queries": fallback_queries[:2] or base_queries[:1],
                "top_k": min(planned_top_k + 2, 8),
                "candidate_k": min(max(planned_candidate_k, planned_top_k * 2), 16),
                "goal": "fallback_retrieval",
            }
        )

    return {
        "task_type": task_type,
        "selected_scope": selected_scope or scope_type,
        "selected_skill": selected_skill,
        "normalized_query": normalized_query,
        "rewritten_queries": base_queries[:max_queries],
        "selected_strategy": selected_strategy,
        "top_k": planned_top_k,
        "candidate_k": planned_candidate_k,
        "prefer_diversity": prefer_diversity,
        "scopes": {
            "scope_type": scope_type,
            "selected_scope": selected_scope or scope_type,
            "file_ids": file_ids or [],
            "strict_mode": strict_mode,
        },
        "candidate_plan": query_plan,
        "fallback_enabled": len(query_plan) > 1,
        "stop_conditions": stop_conditions,
        "workflow_steps": [
            {"step": "route_task_scope_skill", "status": "completed"},
            {"step": "plan_retrieval", "status": "completed", "strategy": selected_strategy},
        ],
    }


def build_session_context(
    *,
    scope_type: str,
    file_ids: list[int] | None,
    task_type: str,
    compare_targets: list[str] | None,
    normalized_query: str,
    selected_scope: str | None = None,
    selected_skill: str | None = None,
    planner_summary: dict[str, Any] | None = None,
    thread_summary: str | None = None,
) -> dict[str, Any]:
    return {
        "scope_type": scope_type,
        "selected_scope": selected_scope or scope_type,
        "file_ids": file_ids or [],
        "task_type": task_type,
        "selected_skill": selected_skill,
        "compare_targets": compare_targets or [],
        "recent_query_summary": normalized_query[:200],
        "last_planner_summary": planner_summary or {},
        "thread_summary": (thread_summary or normalized_query)[:240],
    }


def summarize_tool_trace(tool_name: str, data: dict[str, Any]) -> dict[str, Any]:
    return {"tool": tool_name, "summary": data}
