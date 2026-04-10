from __future__ import annotations

import logging
from datetime import datetime
from threading import Lock

from fastapi import BackgroundTasks
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.file_record import FileRecord
from app.models.pdf_literature import PdfDocument
from app.services.ingest_service import ingest_file_job, mark_ingest_failed_safe
from app.services.pdf_document_service import get_by_file_id, sync_index_status

logger = logging.getLogger(__name__)

# 仅用工进程内集合去重：禁止再用 DB 的 parsing/chunking/embedding 等状态拦截入队，
# 否则 worker 崩溃或 OOM 后 DB 停留在中间态会永久无法重新 schedule（用户看到「待处理」且重试无效）。
_active_ingest_file_ids: set[int] = set()
_active_ingest_lock = Lock()


def is_file_ingest_active(file_id: int) -> bool:
    """当前进程内是否有 ingest 后台任务持有该 file_id（用于 stale 回收避让）。"""
    with _active_ingest_lock:
        return file_id in _active_ingest_file_ids


def schedule_ingest(
    db: Session,
    *,
    file_record: FileRecord,
    background_tasks: BackgroundTasks,
    reset_status: bool = True,
    force: bool = False,
) -> dict:
    with _active_ingest_lock:
        if force:
            _active_ingest_file_ids.discard(file_record.id)
        already_running = file_record.id in _active_ingest_file_ids
        if not already_running:
            _active_ingest_file_ids.add(file_record.id)

    if already_running and not force:
        return {
            "queued": False,
            "index_status": file_record.index_status,
            "skip_reason": "ingest_already_running_in_worker",
        }

    if reset_status:
        now = datetime.utcnow()
        file_record.index_status = "pending"
        file_record.index_error = None
        file_record.index_warning = None
        file_record.indexed_at = None
        file_record.index_run_started_at = None
        file_record.index_status_updated_at = now
        db.commit()
        db.refresh(file_record)

    background_tasks.add_task(_run_ingest_in_background, file_record.id)
    return {"queued": True, "index_status": file_record.index_status, "skip_reason": None}


def _run_ingest_in_background(file_id: int) -> None:
    db = SessionLocal()
    try:
        file_record = db.query(FileRecord).filter(FileRecord.id == file_id).first()
        if not file_record:
            logger.warning("ingest background: file_id=%s missing, skip", file_id)
            return
        try:
            ingest_file_job(db, file_record, prepare_indexing=False)
        except Exception as exc:
            logger.exception("ingest background uncaught file_id=%s", file_id)
            mark_ingest_failed_safe(db, file_id=file_id, error_message=str(exc))
        pdf_doc = get_by_file_id(db, file_id)
        if pdf_doc:
            db.refresh(file_record)
            sync_index_status(db, doc=pdf_doc, file_record=file_record)
    finally:
        with _active_ingest_lock:
            _active_ingest_file_ids.discard(file_id)
        db.close()


def mark_pdf_indexing_pending(db: Session, *, file_record: FileRecord) -> PdfDocument | None:
    pdf_doc = get_by_file_id(db, file_record.id)
    if not pdf_doc:
        return None
    pdf_doc.parse_status = "parsing"
    pdf_doc.parse_progress = 1
    pdf_doc.index_status = "indexing"
    pdf_doc.index_progress = 1
    pdf_doc.parse_error = None
    pdf_doc.index_error = None
    db.commit()
    db.refresh(pdf_doc)
    return pdf_doc
