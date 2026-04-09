"""
轻量 query 理解：规则型 query_type、检索友好 rewrite、子查询与 keyword 视图。
与 route_task_scope_skill 的 task_type 互补；输出结构化 trace 供 retrieval_meta 使用。
"""

from __future__ import annotations

import re
from typing import Any

from app.core.config import settings as app_settings
from app.services.qa_agent_workflow import TASK_COMPARE, extract_compare_targets, normalize_query_text


QUERY_TYPE_FACTUAL = "factual"
QUERY_TYPE_SUMMARY = "summary"
QUERY_TYPE_COMPARE = "compare"
QUERY_TYPE_PROCEDURE = "procedure"
QUERY_TYPE_MULTI_HOP = "multi_hop"
QUERY_TYPE_TROUBLESHOOTING = "troubleshooting"
QUERY_TYPE_OPEN_RISK = "open_or_no_answer_risk"


def _strip_filler_phrases(q: str) -> str:
    s = q.strip()
    for prefix in (
        "请问",
        "麻烦你",
        "麻烦",
        "能否请你",
        "能否",
        "能不能",
        "请帮我",
        "帮我",
        "我想知道",
        "想知道",
        "想请教",
        "请教一下",
        "想问一下",
    ):
        if s.startswith(prefix):
            s = s[len(prefix) :].lstrip("，,：: \t")
    s = re.sub(r"[？?！!]+$", "", s).strip()
    return s or q.strip()


def _keyword_view(q: str) -> str:
    compact = re.sub(r"[^\w\u4e00-\u9fff]+", " ", q, flags=re.UNICODE).strip()
    toks = [t for t in compact.split() if len(t) >= 2]
    if len(toks) >= 8:
        return " ".join(toks[:16])
    return compact if compact else q.strip()


def _classify_query_type(question: str, routing: dict[str, Any]) -> str:
    t = normalize_query_text(question)
    if not t:
        return QUERY_TYPE_FACTUAL
    low = t.lower()

    if routing.get("task_type") == TASK_COMPARE:
        return QUERY_TYPE_COMPARE

    open_signals = (
        "你认为",
        "你怎么看",
        "好不好",
        "是否一定",
        "未来会不会",
        "会不会支持",
        "有没有可能",
        "你怎么看",
        "主观",
        "随便说说",
    )
    if any(s in t for s in open_signals):
        return QUERY_TYPE_OPEN_RISK

    if len(t) <= 4 and "什么" not in t:
        return QUERY_TYPE_OPEN_RISK

    if re.search(r"比较|对比|区别|差异|异同|versus|\bvs\b|哪个更|哪一种更", low):
        return QUERY_TYPE_COMPARE

    if re.search(
        r"如何|怎么|怎样|步骤|流程|操作指南|手把手|安装|配置步骤|怎样设置|如何设置",
        t,
    ):
        return QUERY_TYPE_PROCEDURE

    if re.search(
        r"为什么|为何|怎么办|失败|报错|错误码|无法|不能|异常|不工作|排查|原因|触发条件|解决不了",
        t,
    ):
        return QUERY_TYPE_TROUBLESHOOTING

    if re.search(r"总结|概括|概述|简要|归纳|总体|整体来讲", t):
        return QUERY_TYPE_SUMMARY

    if len(t) > 18 and re.search(r"分别|以及|还有|同时|综合|多个|各自|另外", t):
        return QUERY_TYPE_MULTI_HOP

    return QUERY_TYPE_FACTUAL


def _build_sub_queries(
    query_type: str,
    question: str,
    routing: dict[str, Any],
    rewritten: str,
) -> list[str]:
    max_sub = max(0, int(app_settings.qa_max_sub_queries))
    if max_sub == 0:
        return []

    out: list[str] = []

    if query_type == QUERY_TYPE_COMPARE:
        targets = list(routing.get("compare_targets") or [])
        if len(targets) < 2:
            targets = extract_compare_targets(question)
        for a in targets[:2]:
            a = str(a).strip()
            if a and len(a) > 1:
                out.append(f"{a} 是什么 主要特点")
        if rewritten:
            out.append(rewritten)

    elif query_type == QUERY_TYPE_TROUBLESHOOTING:
        base = rewritten or question.strip()
        candidates = [
            base,
            f"{base} 原因",
            f"{base} 解决方法 排查",
        ]
        for c in candidates:
            c = c.strip()
            if c and c not in out:
                out.append(c)

    elif query_type in (QUERY_TYPE_MULTI_HOP, QUERY_TYPE_SUMMARY):
        parts = re.split(r"[，、；;]\s*", rewritten or question)
        parts = [p.strip() for p in parts if len(p.strip()) > 5]
        out.extend(parts[:max_sub])

    dedup: list[str] = []
    seen: set[str] = set()
    for q in out:
        k = q.strip()
        if not k or k in seen:
            continue
        seen.add(k)
        dedup.append(k)
        if len(dedup) >= max_sub:
            break
    return dedup


def build_query_analysis(
    question: str,
    *,
    routing: dict[str, Any],
    normalized_query: str,
    base_variants: list[str],
) -> dict[str, Any]:
    """
    返回结构化分析 + retrieval_queries（供 plan_retrieval.rewritten_queries 使用）。
    当 qa_enable_query_rewrite=False 时，仅标注 query_type，检索仍用 base_variants。
    """
    original = normalized_query or normalize_query_text(question)
    rewrite_on = bool(app_settings.qa_enable_query_rewrite)
    trace_verbose = bool(app_settings.qa_query_rewrite_trace_enabled)

    query_type = _classify_query_type(question, routing)
    analysis_notes: list[str] = []

    if not rewrite_on:
        retrieval = [q for q in base_variants if q.strip()] or ([original] if original else [])
        return {
            "original_query": original,
            "query_type": query_type,
            "rewritten_query": original,
            "keyword_query": "",
            "sub_queries": [],
            "analysis_notes": ["query_rewrite_disabled"],
            "retrieval_queries": retrieval,
            "multi_query_merge_used": len(retrieval) > 1,
            "rewrite_enabled": False,
            "trace_verbose": trace_verbose,
        }

    rewritten = _strip_filler_phrases(original)
    if rewritten != original:
        analysis_notes.append("stripped_filler")
    keyword_q = _keyword_view(rewritten)

    sub_queries: list[str] = []
    if query_type == QUERY_TYPE_COMPARE and bool(app_settings.qa_enable_multi_query_for_compare):
        sub_queries = _build_sub_queries(query_type, question, routing, rewritten)
    elif query_type == QUERY_TYPE_TROUBLESHOOTING and bool(app_settings.qa_enable_multi_query_expansion):
        sub_queries = _build_sub_queries(query_type, question, routing, rewritten)
    elif query_type == QUERY_TYPE_MULTI_HOP and bool(app_settings.qa_enable_multi_query_expansion):
        sub_queries = _build_sub_queries(query_type, question, routing, rewritten)
    elif query_type == QUERY_TYPE_SUMMARY and bool(app_settings.qa_enable_multi_query_expansion):
        sub_queries = _build_sub_queries(query_type, question, routing, rewritten)

    max_total = max(1, int(app_settings.qa_max_retrieval_queries))
    retrieval: list[str] = []
    seen: set[str] = set()

    def push(q: str) -> None:
        k = q.strip()
        if not k or k in seen:
            return
        seen.add(k)
        retrieval.append(k)

    push(original)
    push(rewritten)
    for v in base_variants:
        push(v)
    if keyword_q and keyword_q not in (original, rewritten):
        push(keyword_q)
    for sq in sub_queries:
        push(sq)

    retrieval = retrieval[:max_total]
    multi_merge = len(retrieval) > 1

    payload: dict[str, Any] = {
        "original_query": original,
        "query_type": query_type,
        "rewritten_query": rewritten,
        "keyword_query": (keyword_q if keyword_q != rewritten else "") or "",
        "sub_queries": sub_queries,
        "analysis_notes": analysis_notes,
        "retrieval_queries": retrieval,
        "multi_query_merge_used": multi_merge,
        "rewrite_enabled": True,
        "trace_verbose": trace_verbose,
    }
    return payload


def compact_query_trace_for_meta(full: dict[str, Any]) -> dict[str, Any]:
    """写入 retrieval_meta 的精简字段（默认始终可带）。"""
    out = {
        "query_type": full.get("query_type"),
        "rewrite_enabled": full.get("rewrite_enabled"),
        "rewritten_query": full.get("rewritten_query"),
        "retrieval_query_count": len(full.get("retrieval_queries") or []),
        "multi_query_merge_used": full.get("multi_query_merge_used"),
    }
    if full.get("trace_verbose"):
        out["keyword_query"] = full.get("keyword_query")
        out["sub_queries"] = full.get("sub_queries")
        out["final_retrieval_queries"] = full.get("retrieval_queries")
        out["analysis_notes"] = full.get("analysis_notes")
    return out
