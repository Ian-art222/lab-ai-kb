from __future__ import annotations

from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.models.file_record import FileRecord
from app.models.knowledge import QACitation, QARetrievalTrace
from app.schemas.diagnostics import TraceListItem, TraceListResponse
from app.services.ingest_service import ingest_file_job

_ACTIVE_INDEXING_STATUSES = {"parsing", "chunking", "embedding", "reindexing", "indexing"}


def _extract_source_file_ids(selected_evidence: list | None, evidence_bundles: dict | None) -> list[int]:
    file_ids: set[int] = set()

    def consume_candidate(item):
        if not isinstance(item, dict):
            return
        value = item.get("file_id") or item.get("source_file_id")
        try:
            if value is not None:
                file_ids.add(int(value))
        except (TypeError, ValueError):
            return

    for evidence in selected_evidence or []:
        consume_candidate(evidence)

    if isinstance(evidence_bundles, dict):
        for _, bundle in evidence_bundles.items():
            if isinstance(bundle, list):
                for item in bundle:
                    consume_candidate(item)
            elif isinstance(bundle, dict):
                consume_candidate(bundle)

    return sorted(file_ids)




def _extract_guardrail_events(tool_traces: list | None) -> list[dict]:
    events: list[dict] = []
    for item in tool_traces or []:
        if not isinstance(item, dict):
            continue
        tool = item.get("tool")
        if tool and "guardrail" in str(tool):
            events.append(item)
    return events

def list_traces(
    db: Session,
    *,
    trace_id: str | None,
    request_id: str | None,
    session_id: int | None,
    start_at: datetime | None,
    end_at: datetime | None,
    is_abstained: bool | None,
    failed: bool | None,
    file_id: int | None,
    limit: int,
    offset: int,
) -> TraceListResponse:
    q = db.query(QARetrievalTrace)
    if trace_id:
        q = q.filter(QARetrievalTrace.trace_id == trace_id)
    if request_id:
        q = q.filter(QARetrievalTrace.request_id == request_id)
    if session_id is not None:
        q = q.filter(QARetrievalTrace.session_id == session_id)
    if start_at is not None:
        q = q.filter(QARetrievalTrace.created_at >= start_at)
    if end_at is not None:
        q = q.filter(QARetrievalTrace.created_at <= end_at)
    if is_abstained is not None:
        q = q.filter(QARetrievalTrace.is_abstained.is_(is_abstained))
    if failed is not None:
        q = q.filter(QARetrievalTrace.failed.is_(failed))
    if file_id is not None:
        q = q.join(
            QACitation,
            QACitation.message_id == QARetrievalTrace.assistant_message_id,
        ).filter(QACitation.file_id == file_id)

    total = q.with_entities(func.count(QARetrievalTrace.id)).scalar() or 0
    rows = q.order_by(QARetrievalTrace.created_at.desc()).offset(offset).limit(limit).all()
    items = [
        {
            "trace_id": row.trace_id,
            "request_id": row.request_id,
            "session_id": row.session_id,
            "question": row.question,
            "normalized_query": row.normalized_query,
            "rewritten_queries": row.rewritten_queries_json,
            "retrieval_strategy": row.retrieval_strategy,
            "filters": row.filters_json,
            "selected_evidence": row.selected_evidence_json,
            "evidence_bundles": row.evidence_bundles_json,
            "strict_mode": row.strict_mode,
            "is_abstained": row.is_abstained,
            "abstain_reason": row.abstain_reason,
            "failed": row.failed,
            "failure_reason": row.failure_reason,
            "model_name": row.model_name,
            "token_usage": row.token_usage_json,
            "latency_ms": row.latency_ms,
            "latency_breakdown": row.latency_breakdown_json,
            "task_type": row.task_type,
            "tool_traces": row.tool_traces_json,
            "workflow_steps": row.workflow_steps_json,
            "session_context": row.session_context_json,
            "selected_scope": (row.debug_json or {}).get("selected_scope") if isinstance(row.debug_json, dict) else None,
            "selected_skill": (row.debug_json or {}).get("selected_skill") if isinstance(row.debug_json, dict) else None,
            "planner_meta": (row.debug_json or {}).get("planner_meta") if isinstance(row.debug_json, dict) else None,
            "guardrail_events": _extract_guardrail_events(row.tool_traces_json),
            "created_at": row.created_at,
            "source_file_ids": _extract_source_file_ids(row.selected_evidence_json, row.evidence_bundles_json),
        }
        for row in rows
    ]
    return TraceListResponse(total=total, limit=limit, offset=offset, items=items)


def get_trace_detail(db: Session, *, trace_id: str) -> dict:
    row = db.query(QARetrievalTrace).filter(QARetrievalTrace.trace_id == trace_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="trace 不存在")
    return {
        "trace_id": row.trace_id,
        "request_id": row.request_id,
        "session_id": row.session_id,
        "question": row.question,
        "normalized_query": row.normalized_query,
        "rewritten_queries": row.rewritten_queries_json,
        "retrieval_strategy": row.retrieval_strategy,
        "filters": row.filters_json,
        "selected_evidence": row.selected_evidence_json,
        "evidence_bundles": row.evidence_bundles_json,
        "strict_mode": row.strict_mode,
        "is_abstained": row.is_abstained,
        "abstain_reason": row.abstain_reason,
        "failed": row.failed,
        "failure_reason": row.failure_reason,
        "model_name": row.model_name,
        "token_usage": row.token_usage_json,
        "latency_ms": row.latency_ms,
        "latency_breakdown": row.latency_breakdown_json,
        "task_type": row.task_type,
        "tool_traces": row.tool_traces_json,
        "workflow_steps": row.workflow_steps_json,
        "session_context": row.session_context_json,
        "selected_scope": (row.debug_json or {}).get("selected_scope") if isinstance(row.debug_json, dict) else None,
        "selected_skill": (row.debug_json or {}).get("selected_skill") if isinstance(row.debug_json, dict) else None,
        "planner_meta": (row.debug_json or {}).get("planner_meta") if isinstance(row.debug_json, dict) else None,
        "guardrail_events": _extract_guardrail_events(row.tool_traces_json),
        "debug_json": row.debug_json,
        "created_at": row.created_at,
        "source_file_ids": _extract_source_file_ids(row.selected_evidence_json, row.evidence_bundles_json),
    }


def retry_or_reindex_file(db: Session, *, file_id: int, force_reindex: bool) -> FileRecord:
    file_record = db.query(FileRecord).filter(FileRecord.id == file_id).first()
    if not file_record:
        raise HTTPException(status_code=404, detail="文件不存在")

    if file_record.index_status in _ACTIVE_INDEXING_STATUSES:
        return file_record

    if file_record.index_status == "indexed" and not force_reindex:
        return file_record

    file_record.index_status = "reindexing" if force_reindex else "pending"
    file_record.last_error = None
    file_record.last_error_code = None
    if file_record.index_status != "indexed":
        file_record.retry_count = int(file_record.retry_count or 0) + 1
    db.commit()
    db.refresh(file_record)

    return ingest_file_job(db, file_record, prepare_indexing=True)


def list_reason_code_stats(db: Session) -> list[dict[str, int | str]]:
    rows = (
        db.query(
            func.coalesce(QARetrievalTrace.abstain_reason, QARetrievalTrace.failure_reason).label("reason_code"),
            func.count(QARetrievalTrace.id).label("count"),
        )
        .filter(
            or_(
                QARetrievalTrace.abstain_reason.is_not(None),
                QARetrievalTrace.failure_reason.is_not(None),
            )
        )
        .group_by("reason_code")
        .order_by(func.count(QARetrievalTrace.id).desc())
        .all()
    )
    return [{"reason_code": str(reason), "count": int(count)} for reason, count in rows if reason]


def export_trace(db: Session, *, trace_id: str) -> dict:
    detail = get_trace_detail(db, trace_id=trace_id)
    trace = TraceListItem.model_validate(detail)
    return {
        "trace": trace.model_dump(mode="json"),
        "source_file_ids": detail.get("source_file_ids", []),
    }
