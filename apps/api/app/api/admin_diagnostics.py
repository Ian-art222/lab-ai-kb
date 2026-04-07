from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.auth import require_admin
from app.db.session import get_db
from app.models.user import User
from app.schemas.diagnostics import RetryIndexResponse, TraceListResponse
from app.services.diagnostics_service import get_trace_detail, list_traces, retry_or_reindex_file

router = APIRouter(prefix="/api/admin/diagnostics", tags=["admin-diagnostics"])


@router.get("/traces", response_model=TraceListResponse)
def get_traces(
    trace_id: str | None = None,
    request_id: str | None = None,
    session_id: int | None = None,
    start_at: datetime | None = Query(default=None),
    end_at: datetime | None = Query(default=None),
    is_abstained: bool | None = None,
    failed: bool | None = None,
    file_id: int | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    return list_traces(
        db,
        trace_id=trace_id,
        request_id=request_id,
        session_id=session_id,
        start_at=start_at,
        end_at=end_at,
        is_abstained=is_abstained,
        failed=failed,
        file_id=file_id,
        limit=limit,
        offset=offset,
    )


@router.get("/traces/{trace_id}")
def get_trace(
    trace_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    return get_trace_detail(db, trace_id=trace_id)


@router.post("/files/{file_id}/retry-index", response_model=RetryIndexResponse)
def retry_index(
    file_id: int,
    force_reindex: bool = False,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    file_record = retry_or_reindex_file(db, file_id=file_id, force_reindex=force_reindex)
    return {
        "file_id": file_record.id,
        "status": file_record.index_status,
        "retry_count": file_record.retry_count,
        "last_error_code": file_record.last_error_code,
    }
