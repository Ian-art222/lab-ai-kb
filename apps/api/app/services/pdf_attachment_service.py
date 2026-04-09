from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.pdf_literature import DocumentAttachment, PdfDocument


def list_attachments(db: Session, *, doc: PdfDocument) -> list[DocumentAttachment]:
    return (
        db.query(DocumentAttachment)
        .filter(DocumentAttachment.doc_id == doc.id)
        .order_by(DocumentAttachment.sort_order.asc(), DocumentAttachment.id.asc())
        .all()
    )


def add_attachment(
    db: Session,
    *,
    doc: PdfDocument,
    file_id: int,
    attachment_type: str,
    title: str | None,
    created_by: int | None,
) -> DocumentAttachment:
    existing = (
        db.query(DocumentAttachment)
        .filter(DocumentAttachment.doc_id == doc.id, DocumentAttachment.file_id == file_id)
        .first()
    )
    if existing:
        return existing
    max_order = db.query(DocumentAttachment.sort_order).filter(DocumentAttachment.doc_id == doc.id).order_by(DocumentAttachment.sort_order.desc()).first()
    sort_order = int(max_order[0]) + 1 if max_order and max_order[0] is not None else 0
    row = DocumentAttachment(
        doc_id=doc.id,
        file_id=file_id,
        attachment_type=attachment_type or "supplement",
        title=title,
        sort_order=sort_order,
        created_by=created_by,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def remove_attachment(db: Session, *, attachment: DocumentAttachment) -> None:
    db.delete(attachment)
    db.commit()
