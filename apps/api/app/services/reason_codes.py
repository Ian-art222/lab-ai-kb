from __future__ import annotations

from enum import Enum


class QAReasonCode(str, Enum):
    NO_RETRIEVAL_HIT = "no_retrieval_hit"
    LOW_RETRIEVAL_CONFIDENCE = "low_retrieval_confidence"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    CONFLICTING_EVIDENCE = "conflicting_evidence"
    STRICT_MODE_BLOCKED = "strict_mode_blocked"
    MODEL_GENERATION_FAILED = "model_generation_failed"
    RETRIEVAL_FAILED = "retrieval_failed"
    RERANK_FAILED = "rerank_failed"
    TIMEOUT = "timeout"
    INTERNAL_ERROR = "internal_error"


_REASON_MESSAGE_MAP: dict[QAReasonCode, str] = {
    QAReasonCode.NO_RETRIEVAL_HIT: "未检索到可用知识片段",
    QAReasonCode.LOW_RETRIEVAL_CONFIDENCE: "检索结果置信度不足",
    QAReasonCode.INSUFFICIENT_EVIDENCE: "证据不足，无法给出可靠回答",
    QAReasonCode.CONFLICTING_EVIDENCE: "检索到互相冲突的证据",
    QAReasonCode.STRICT_MODE_BLOCKED: "严格模式下证据校验未通过",
    QAReasonCode.MODEL_GENERATION_FAILED: "模型生成失败",
    QAReasonCode.RETRIEVAL_FAILED: "检索阶段失败",
    QAReasonCode.RERANK_FAILED: "重排阶段失败",
    QAReasonCode.TIMEOUT: "请求超时",
    QAReasonCode.INTERNAL_ERROR: "系统内部错误",
}


_LEGACY_TO_REASON_CODE: dict[str, QAReasonCode] = {
    "no_candidates": QAReasonCode.NO_RETRIEVAL_HIT,
    "no_compatible_content": QAReasonCode.NO_RETRIEVAL_HIT,
    "low_confidence_retrieval": QAReasonCode.LOW_RETRIEVAL_CONFIDENCE,
    "insufficient_citations": QAReasonCode.INSUFFICIENT_EVIDENCE,
    "grounding_guard": QAReasonCode.STRICT_MODE_BLOCKED,
    "MODEL_REQUEST_FAILED": QAReasonCode.MODEL_GENERATION_FAILED,
}


def normalize_reason_code(reason: str | None) -> QAReasonCode | None:
    if not reason:
        return None
    value = reason.strip()
    if not value:
        return None
    for code in QAReasonCode:
        if code.value == value:
            return code
    return _LEGACY_TO_REASON_CODE.get(value)


def reason_code_message(reason: str | QAReasonCode | None) -> str | None:
    code = normalize_reason_code(reason if isinstance(reason, str) else (reason.value if reason else None))
    if code is None:
        return None
    return _REASON_MESSAGE_MAP.get(code)
