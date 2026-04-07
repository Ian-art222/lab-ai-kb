from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.models.knowledge import QARetrievalTrace


def list_traces(
    db: Session,
    *,
    trace_id: str | None = None,
    request_id: str | None = None,
    session_id: int | None = None,
    from_time: datetime | None = None,
    to_time: datetime | None = None,
    abstained: bool | None = None,
    failed: bool | None = None,
    limit: int = 50,
) -> tuple[int, list[QARetrievalTrace]]:
    query = db.query(QARetrievalTrace)
    if trace_id:
        query = query.filter(QARetrievalTrace.trace_id == trace_id)
    if request_id:
        query = query.filter(QARetrievalTrace.request_id == request_id)
    if session_id is not None:
        query = query.filter(QARetrievalTrace.session_id == session_id)
    if from_time is not None:
        query = query.filter(QARetrievalTrace.created_at >= from_time)
    if to_time is not None:
        query = query.filter(QARetrievalTrace.created_at <= to_time)
    if abstained is not None:
        query = query.filter(QARetrievalTrace.is_abstained.is_(abstained))
    if failed is not None:
        if failed:
            query = query.filter(QARetrievalTrace.failure_reason.is_not(None))
        else:
            query = query.filter(QARetrievalTrace.failure_reason.is_(None))

    total = query.count()
    rows = query.order_by(QARetrievalTrace.created_at.desc(), QARetrievalTrace.id.desc()).limit(max(1, min(limit, 200))).all()
    return total, rows

