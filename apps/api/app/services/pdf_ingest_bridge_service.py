from __future__ import annotations

from threading import Lock

from fastapi import BackgroundTasks
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.file_record import FileRecord
from app.models.pdf_literature import PdfDocument
from app.services.ingest_service import ingest_file_job
from app.services.pdf_document_service import get_by_file_id, sync_index_status

_ACTIVE_INDEX_STATUSES = {"indexing", "parsing", "chunking", "embedding", "reindexing"}
_active_ingest_file_ids: set[int] = set()
_active_ingest_lock = Lock()


def schedule_ingest(
    db: Session,
    *,
    file_record: FileRecord,
    background_tasks: BackgroundTasks,
    reset_status: bool = True,
) -> dict:
    with _active_ingest_lock:
        already_running = (
            file_record.id in _active_ingest_file_ids
            or (file_record.index_status or "") in _ACTIVE_INDEX_STATUSES
        )
        if not already_running:
            _active_ingest_file_ids.add(file_record.id)

    if already_running:
        return {"queued": False, "index_status": file_record.index_status}

    if reset_status:
        file_record.index_status = "pending"
        file_record.index_error = None
        file_record.index_warning = None
        file_record.indexed_at = None
        db.commit()
        db.refresh(file_record)

    background_tasks.add_task(_run_ingest_in_background, file_record.id)
    return {"queued": True, "index_status": file_record.index_status}


def _run_ingest_in_background(file_id: int) -> None:
    db = SessionLocal()
    try:
        file_record = db.query(FileRecord).filter(FileRecord.id == file_id).first()
        if not file_record:
            return
        ingest_file_job(db, file_record, prepare_indexing=False)
        pdf_doc = get_by_file_id(db, file_id)
        if pdf_doc:
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
