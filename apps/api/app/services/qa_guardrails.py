from __future__ import annotations

from collections import Counter
from typing import Any


def apply_input_guardrail(question: str) -> dict[str, Any]:
    text = (question or "").lower()
    risky_tokens = ["ignore system", "系统提示", "越权", "联网搜索", "browser", "调用工具", "computer use"]
    hits = [token for token in risky_tokens if token in text]
    return {
        "triggered": bool(hits),
        "severity": "high" if hits else "none",
        "action": "constrain_to_text_kb" if hits else "allow",
        "matched_rules": hits,
    }


def apply_evidence_guardrail(references: list[dict] | None) -> dict[str, Any]:
    refs = references or []
    suspicious = 0
    for ref in refs:
        snippet = str(ref.get("snippet", "")).lower()
        if "ignore" in snippet and "instruction" in snippet:
            suspicious += 1
        if "调用" in snippet and "工具" in snippet:
            suspicious += 1
    return {
        "triggered": suspicious > 0,
        "suspicious_chunks": suspicious,
        "action": "treat_as_content_not_instruction" if suspicious else "allow",
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
    if dominant_ratio >= 0.8 and len(file_counter) > 1:
        warnings.append("single_source_dominance")
    if compare_mode and len(file_counter) <= 1:
        warnings.append("compare_evidence_asymmetric")

    return {
        "triggered": bool(warnings),
        "warnings": warnings,
        "dominant_source_ratio": dominant_ratio,
        "source_count": len(file_counter),
        "action": "append_caution" if warnings else "allow",
    }
