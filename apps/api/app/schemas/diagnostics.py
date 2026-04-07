from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class TraceListItem(BaseModel):
    trace_id: str
    request_id: str | None = None
    session_id: int
    question: str
    normalized_query: str | None = None
    rewritten_queries: list[str] | None = None
    retrieval_strategy: str | None = None
    filters: dict[str, Any] | None = None
    selected_evidence: list[dict[str, Any]] | None = None
    evidence_bundles: dict[str, Any] | None = None
    strict_mode: bool | None = None
    is_abstained: bool
    abstain_reason: str | None = None
    failed: bool
    failure_reason: str | None = None
    model_name: str | None = None
    token_usage: dict[str, Any] | None = None
    latency_ms: int | None = None
    latency_breakdown: dict[str, Any] | None = None
    task_type: str | None = None
    tool_traces: list[dict[str, Any]] | None = None
    workflow_steps: list[dict[str, Any]] | None = None
    session_context: dict[str, Any] | None = None
    created_at: datetime


class TraceListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[TraceListItem]


class RetryIndexResponse(BaseModel):
    file_id: int
    status: str
    retry_count: int
    last_error_code: str | None = None


class TraceReasonStatItem(BaseModel):
    reason_code: str
    count: int


class TraceExportResponse(BaseModel):
    trace: TraceListItem
    source_file_ids: list[int] = []
