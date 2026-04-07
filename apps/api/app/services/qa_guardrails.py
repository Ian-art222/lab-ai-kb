from __future__ import annotations

from collections import Counter
from typing import Any


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
