from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class TraceItem(BaseModel):
    id: int
    trace_id: str | None = None
    request_id: str | None = None
    session_id: int
    question: str
    retrieval_mode: str | None = None
    fusion_method: str | None = None
    answer_source: str | None = None
    is_abstained: bool | None = None
    abstain_reason: str | None = None
    failure_reason: str | None = None
    model_name: str | None = None
    latency_ms: float | None = None
    evidence_bundles_json: dict | None = None
    filters_json: dict | None = None
    token_usage_json: dict | None = None
    tool_traces_json: list | dict | None = None
    workflow_steps_json: list | dict | None = None
    session_context_json: dict | None = None
    debug_json: dict | None = None
    created_at: datetime


class TraceListResponse(BaseModel):
    total: int
    items: list[TraceItem]


class FileRetryResponse(BaseModel):
    file_id: int
    index_status: str
    retry_count: int
    last_error_code: str | None = None
    indexed_at: datetime | None = None
    index_error: str | None = None
    extra: Any | None = None

