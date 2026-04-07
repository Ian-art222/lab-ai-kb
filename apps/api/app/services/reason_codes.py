from __future__ import annotations

from enum import Enum


class ReasonCode(str, Enum):
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

