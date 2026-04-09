from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.file_record import FileRecord
from app.models.pdf_literature import PdfDocument


class PdfDocumentServiceError(RuntimeError):
    pass


def get_by_file_id(db: Session, file_id: int) -> PdfDocument | None:
    return db.query(PdfDocument).filter(PdfDocument.file_id == file_id).first()


def ensure_pdf_document(
    db: Session,
    *,
    file_record: FileRecord,
    created_by: int | None,
) -> PdfDocument:
    if (file_record.file_type or "").lower() != "pdf":
        raise PdfDocumentServiceError("仅 PDF 文件可创建文献对象")

    existing = get_by_file_id(db, file_record.id)
    if existing:
        return existing

    doc = PdfDocument(
        file_id=file_record.id,
        title=file_record.file_name,
        language="auto",
        parse_status="pending",
        parse_progress=0,
        index_status=file_record.index_status or "pending",
        index_progress=0,
        created_by=created_by,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc


def sync_index_status(db: Session, *, doc: PdfDocument, file_record: FileRecord) -> PdfDocument:
    status = file_record.index_status or "pending"
    doc.index_status = status
    doc.parse_status = "completed" if status in {"indexed", "partial_failed"} else (
        "failed" if status == "failed" else "parsing"
    )
    if status in {"indexed", "partial_failed", "failed"}:
        doc.parse_progress = 100
        doc.index_progress = 100 if status in {"indexed", "partial_failed"} else 0
        doc.index_error = file_record.index_error
        doc.parse_error = file_record.index_error
    db.commit()
    db.refresh(doc)
    return doc
