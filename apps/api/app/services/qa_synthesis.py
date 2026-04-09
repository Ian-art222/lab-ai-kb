"""
按 query_type / task 组织答案结构与证据约束说明（注入到 LLM user prompt，非替代检索逻辑）。
"""

from __future__ import annotations

from typing import Any

from app.core.config import settings as app_settings
from app.services.qa_agent_workflow import TASK_COMPARE, TASK_MULTI_DOC_SYNTHESIS
from app.services.query_understanding import (
    QUERY_TYPE_COMPARE,
    QUERY_TYPE_FACTUAL,
    QUERY_TYPE_MULTI_HOP,
    QUERY_TYPE_OPEN_RISK,
    QUERY_TYPE_PROCEDURE,
    QUERY_TYPE_SUMMARY,
    QUERY_TYPE_TROUBLESHOOTING,
)


def _style_for_query_type(query_type: str) -> str:
    return {
        QUERY_TYPE_FACTUAL: (
            "【回答结构-事实型】\n"
            "1) 先用一两句话直接回答核心问题。\n"
            "2) 用要点列出关键依据，并说明对应资料中的表述（不要编造未出现的细节）。\n"
            "3) 若资料仅能部分覆盖问题，必须明确写出「现有资料不足以完整确认」并说明缺口。"
        ),
        QUERY_TYPE_SUMMARY: (
            "【回答结构-总结型】\n"
            "1) 先给出总体概括（基于资料，不要假装穷尽所有文件）。\n"
            "2) 再分主题归纳；若某主题无资料支撑，标注「资料未涉及」。\n"
            "3) 区分「资料明确记载」与「基于片段的合理归纳」，后者需弱化语气。"
        ),
        QUERY_TYPE_COMPARE: (
            "【回答结构-比较型】\n"
            "1) 明确比较对象（若资料未命名对象，用「资料中的方案A/B」指代并说明局限）。\n"
            "2) 分「共同点」「差异点」「结论/适用场景」三节输出；不要写成单一长段落。\n"
            "3) 若两侧证据不对称，必须在结论前点明。"
        ),
        QUERY_TYPE_PROCEDURE: (
            "【回答结构-步骤型】\n"
            "1) 按顺序用编号步骤写出操作流程，尽量保留资料中的顺序与条件。\n"
            "2) 如有前置条件、注意事项、例外情况，单列一小节。\n"
            "3) 资料缺失的步骤用「资料未给出第N步」标出，不要臆造。"
        ),
        QUERY_TYPE_TROUBLESHOOTING: (
            "【回答结构-排查型】\n"
            "1) 先列出资料中提到的可能原因或触发条件（分点）。\n"
            "2) 再给排查/解决路径；如资料只有现象无原因，明确说明不能武断归因。\n"
            "3) 禁止在证据不足时给出「一定是…」式结论。"
        ),
        QUERY_TYPE_MULTI_HOP: (
            "【回答结构-综合型】\n"
            "1) 说明答案整合了多个段落/来源；分点对应不同方面。\n"
            "2) 不要只复述第一条资料；若资料相互补充，要串起来。\n"
            "3) 无法从资料串出逻辑链时，承认缺口。"
        ),
        QUERY_TYPE_OPEN_RISK: (
            "【回答结构-高风险泛问】\n"
            "1) 优先依据资料中能直接支撑的部分；资料未覆盖的推断必须显著弱化。\n"
            "2) 不要对主观判断、未来预测做肯定表述；使用「资料未涉及」「无法从现有资料确认」。"
        ),
    }.get(query_type, _style_for_query_type(QUERY_TYPE_FACTUAL))


def build_answer_synthesis_addon(
    *,
    query_type: str,
    task_type: str,
    sufficiency: dict[str, Any],
    conflict_hint: dict[str, Any],
    reference_count: int,
    distinct_files: int,
    coverage_assessment: dict[str, Any] | None = None,
    strict_mode: bool = False,
) -> tuple[str, dict[str, Any]]:
    """返回 (注入到 user prompt 的文本段, trace dict)。"""
    parts: list[str] = []
    trace: dict[str, Any] = {
        "query_type": query_type,
        "task_type": task_type,
        "style_addon_applied": False,
        "sufficiency_level": sufficiency.get("level"),
        "sufficiency_prefix_applied": False,
        "conflict_notice_applied": False,
        "coverage_assessment": None,
        "coverage_shortfall": None,
        "requires_multi_source_but_missing": None,
        "dominant_source_warning": None,
        "citation_source_count": distinct_files,
    }

    if bool(app_settings.qa_enable_answer_style_by_query_type):
        st = _style_for_query_type(query_type)
        if task_type == TASK_COMPARE and query_type != QUERY_TYPE_COMPARE:
            st = _style_for_query_type(QUERY_TYPE_COMPARE)
        if task_type == TASK_MULTI_DOC_SYNTHESIS:
            st += "\n（本题偏好多来源综合，请在段落中体现不同来源的要点。）"
        parts.append(st)
        trace["style_addon_applied"] = True

    if bool(app_settings.qa_enable_evidence_sufficiency_guard):
        lvl = sufficiency.get("level")
        if lvl == "weak":
            parts.append(
                "【证据强度提示】\n"
                "当前检索/引用支撑偏弱：请在答案开头用一两句话说明「现有资料仅能部分回答或无法直接确认」，"
                "后续内容仅限资料中明确出现的表述；禁止装作已充分验证。"
            )
            trace["sufficiency_prefix_applied"] = True
        elif lvl == "medium" and reference_count <= 1:
            parts.append(
                "【证据强度提示】\n"
                "当前主要仅依赖少量片段：结论需保守，避免过度概括；可提示用户补充资料复核。"
            )
            trace["sufficiency_prefix_applied"] = True

    if bool(app_settings.qa_enable_conflict_notice) and conflict_hint.get("likely_conflict"):
        parts.append(
            "【来源一致性】\n"
            "检测到不同资料片段可能存在表述冲突或侧重点不一致：请在答案中单列一小节「资料不一致/需人工核对」，"
            "分别概括不同说法，不要强行合并成单一确定结论。"
        )
        trace["conflict_notice_applied"] = True
        trace["conflict_detail"] = conflict_hint

    if distinct_files >= 2 and query_type in (QUERY_TYPE_SUMMARY, QUERY_TYPE_MULTI_HOP, QUERY_TYPE_TROUBLESHOOTING):
        parts.append(
            "【多来源】\n"
            "资料来自多个文件：请避免只复述其中一个文件；如某文件无相关信息请说明。"
        )

    if coverage_assessment:
        trace["coverage_assessment"] = coverage_assessment.get("coverage_assessment")
        trace["coverage_shortfall"] = bool(coverage_assessment.get("coverage_shortfall"))
        trace["requires_multi_source_but_missing"] = bool(coverage_assessment.get("requires_multi_source_but_missing"))
        trace["dominant_source_warning"] = bool(coverage_assessment.get("dominant_source_warning"))
        trace["citation_source_count"] = int(coverage_assessment.get("distinct_files_observed") or distinct_files)

    sensitive = (
        QUERY_TYPE_COMPARE,
        QUERY_TYPE_SUMMARY,
        QUERY_TYPE_MULTI_HOP,
        QUERY_TYPE_TROUBLESHOOTING,
    )
    if (
        bool(app_settings.qa_enable_coverage_shortfall_guard)
        and coverage_assessment
        and query_type in sensitive
    ):
        ca = str(coverage_assessment.get("coverage_assessment") or "")
        if ca in ("coverage_limited", "coverage_poor"):
            strict_note = "严格模式：禁止做出跨文献的强比较或总结性定论。\n" if strict_mode else ""
            parts.append(
                "【资料覆盖局限】\n"
                f"{strict_note}"
                "当前上下文可能主要来自少量来源或单一文件占比偏高：不要过度泛化；须在答案中明确说明「结论仅基于当前资料范围」；"
                "比较类问题若资料不足以覆盖比较对象两侧，应直接写明「现有资料不足以支持稳健比较/归纳」，不要勉强下结论。"
            )
            trace["coverage_shortfall_prompt_applied"] = True

    text = "\n\n".join(parts) if parts else ""
    return text, trace
