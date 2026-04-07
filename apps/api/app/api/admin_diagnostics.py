from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.db.session import get_db
from app.models.file_record import FileRecord
from app.models.user import User
from app.schemas.trace import FileRetryResponse, TraceItem, TraceListResponse
from app.services.ingest_service import ingest_file_job
from app.services.trace_service import list_traces

router = APIRouter(prefix="/api/admin/diagnostics", tags=["admin-diagnostics"])


def _require_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可访问该接口")
    return current_user


@router.get("/traces", response_model=TraceListResponse)
def get_traces(
    trace_id: str | None = None,
    request_id: str | None = None,
    session_id: int | None = None,
    from_time: datetime | None = Query(default=None),
    to_time: datetime | None = Query(default=None),
    abstained: bool | None = None,
    failed: bool | None = None,
    limit: int = 50,
    db: Session = Depends(get_db),
    _: User = Depends(_require_admin),
):
    total, rows = list_traces(
        db,
        trace_id=trace_id,
        request_id=request_id,
        session_id=session_id,
        from_time=from_time,
        to_time=to_time,
        abstained=abstained,
        failed=failed,
        limit=limit,
    )
    return {"total": total, "items": [TraceItem.model_validate(row, from_attributes=True) for row in rows]}


@router.get("/traces/{trace_id}", response_model=TraceItem)
def get_trace_detail(
    trace_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(_require_admin),
):
    total, rows = list_traces(db, trace_id=trace_id, limit=1)
    if total < 1 or not rows:
        raise HTTPException(status_code=404, detail="trace 不存在")
    return TraceItem.model_validate(rows[0], from_attributes=True)


@router.post("/files/{file_id}/retry-index", response_model=FileRetryResponse)
def retry_file_index(
    file_id: int,
    force_reindex: bool = True,
    db: Session = Depends(get_db),
    _: User = Depends(_require_admin),
):
    file_record = db.query(FileRecord).filter(FileRecord.id == file_id).first()
    if not file_record:
        raise HTTPException(status_code=404, detail="文件不存在")
    if force_reindex and file_record.index_status not in {"failed", "stale", "indexed"}:
        file_record.index_status = "reindexing"
        db.commit()
        db.refresh(file_record)
    ingest_file_job(db, file_record, prepare_indexing=True)
    db.refresh(file_record)
    return {
        "file_id": file_record.id,
        "index_status": file_record.index_status,
        "retry_count": file_record.retry_count,
        "last_error_code": file_record.last_error_code,
        "indexed_at": file_record.indexed_at,
        "index_error": file_record.index_error,
        "extra": {"pipeline_version": file_record.pipeline_version},
    }

