from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.config import settings
from app.core.permissions import user_may_access_file_record
from app.db.session import get_db
from app.models.file_record import FileRecord
from app.models.pdf_literature import DocumentAttachment, PdfAnnotation
from app.models.user import User
from app.services.pdf_annotation_service import (
    create_annotation,
    delete_annotation,
    list_my_annotations,
    list_public_annotations_with_authors,
    list_public_by_user,
    list_public_users,
    update_annotation,
)
from app.services.pdf_attachment_service import add_attachment, list_attachments, remove_attachment
from app.services.pdf_document_service import ensure_pdf_document, get_by_file_id
from app.services.pdf_export_service import (
    bib_response,
    build_bib,
    build_download_response,
    build_ris,
    ris_response,
)
from app.services.pdf_reader_qa_service import ask_in_pdf

UPLOAD_DIR = Path(settings.upload_dir)

router = APIRouter(prefix="/api/pdf-documents", tags=["pdf-documents"])


class PdfQaRequest(BaseModel):
    question: str
    strict_mode: bool = True
    top_k: int = 6


class AnnotationUpsertRequest(BaseModel):
    is_public: bool = False
    annotation_json: dict


class AttachmentCreateRequest(BaseModel):
    file_id: int
    attachment_type: str = "supplement"
    title: str | None = None


def _ensure_pdf_file(db: Session, current_user: User, file_id: int) -> tuple[FileRecord, object]:
    file_record = db.query(FileRecord).filter(FileRecord.id == file_id).first()
    if not file_record:
        raise HTTPException(status_code=404, detail="文件不存在")
    if not user_may_access_file_record(db, current_user, file_record):
        raise HTTPException(status_code=403, detail="无权访问该文件")
    if (file_record.file_type or "").lower() != "pdf":
        raise HTTPException(status_code=400, detail="仅支持 PDF 文献")
    doc = get_by_file_id(db, file_id) or ensure_pdf_document(db, file_record=file_record, created_by=current_user.id)
    return file_record, doc


def _get_file_storage_path(file_record: FileRecord) -> Path:
    storage_path = file_record.storage_path or file_record.file_name
    return UPLOAD_DIR / storage_path


@router.get("/{file_id}")
def get_document(file_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    file_record, doc = _ensure_pdf_file(db, current_user, file_id)
    return {
        "doc": {
            "id": doc.id,
            "file_id": doc.file_id,
            "title": doc.title,
            "authors_json": doc.authors_json,
            "journal": doc.journal,
            "publication_year": doc.publication_year,
            "doi": doc.doi,
            "abstract_text": doc.abstract_text,
            "language": doc.language,
            "page_count": doc.page_count,
            "parse_status": doc.parse_status,
            "parse_progress": doc.parse_progress,
            "parse_error": doc.parse_error,
            "index_status": file_record.index_status,
            "index_progress": doc.index_progress,
            "index_error": file_record.index_error,
        },
        "file": {
            "id": file_record.id,
            "folder_id": file_record.folder_id,
            "file_name": file_record.file_name,
            "file_type": file_record.file_type,
            "mime_type": file_record.mime_type,
            "index_status": file_record.index_status,
            "can_download": True,
        },
    }


@router.get("/{file_id}/download")
def document_download(
    file_id: int,
    include_original: bool = True,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    file_record, _ = _ensure_pdf_file(db, current_user, file_id)
    return build_download_response(file_record=file_record, include_original=include_original)


@router.get("/{file_id}/content")
def document_content(
    file_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    file_record, _ = _ensure_pdf_file(db, current_user, file_id)
    file_path = _get_file_storage_path(file_record)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="服务器上未找到该文件")
    # 禁止手写 Content-Disposition：非 ASCII 文件名会令 Starlette 用 latin-1 编码头而抛 UnicodeEncodeError。
    # 使用 FileResponse 内置 filename + content_disposition_type，由 Starlette 生成 filename*=utf-8''…
    return FileResponse(
        path=file_path,
        filename=file_record.file_name,
        media_type="application/pdf",
        content_disposition_type="inline",
    )


@router.get("/{file_id}/export/bib")
def export_bib(file_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    file_record, doc = _ensure_pdf_file(db, current_user, file_id)
    content = build_bib(doc, file_record)
    return bib_response(content, f"{Path(file_record.file_name).stem}.bib")


@router.get("/{file_id}/export/ris")
def export_ris(file_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    file_record, doc = _ensure_pdf_file(db, current_user, file_id)
    content = build_ris(doc, file_record)
    return ris_response(content, f"{Path(file_record.file_name).stem}.ris")


@router.get("/{file_id}/annotations/me")
def annotations_me(file_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    _, doc = _ensure_pdf_file(db, current_user, file_id)
    rows = list_my_annotations(db, doc=doc, user_id=current_user.id)
    return [{"id": r.id, "is_public": r.is_public, "annotation_json": r.annotation_json, "version": r.version} for r in rows]


@router.post("/{file_id}/annotations")
def annotations_create(
    file_id: int,
    payload: AnnotationUpsertRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _, doc = _ensure_pdf_file(db, current_user, file_id)
    row = create_annotation(
        db,
        doc=doc,
        user_id=current_user.id,
        annotation_json=payload.annotation_json,
        is_public=payload.is_public,
    )
    return {"id": row.id, "is_public": row.is_public, "annotation_json": row.annotation_json, "version": row.version}


@router.patch("/{file_id}/annotations/{annotation_id}")
def annotations_patch(
    file_id: int,
    annotation_id: int,
    payload: AnnotationUpsertRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _, _ = _ensure_pdf_file(db, current_user, file_id)
    row = db.query(PdfAnnotation).filter(PdfAnnotation.id == annotation_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="批注不存在")
    try:
        row = update_annotation(
            db,
            annotation=row,
            user_id=current_user.id,
            annotation_json=payload.annotation_json,
            is_public=payload.is_public,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return {"id": row.id, "is_public": row.is_public, "annotation_json": row.annotation_json, "version": row.version}


@router.delete("/{file_id}/annotations/{annotation_id}")
def annotations_delete(
    file_id: int,
    annotation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _, _ = _ensure_pdf_file(db, current_user, file_id)
    row = db.query(PdfAnnotation).filter(PdfAnnotation.id == annotation_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="批注不存在")
    try:
        delete_annotation(db, annotation=row, user_id=current_user.id)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return {"ok": True}


@router.get("/{file_id}/annotations/public-users")
def annotations_public_users(file_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    _, doc = _ensure_pdf_file(db, current_user, file_id)
    return {"user_ids": list_public_users(db, doc=doc)}


@router.get("/{file_id}/annotations/lab-public")
def annotations_lab_public(file_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """本文献下所有「实验室可见」批注/笔记（含作者），供阅读器「他人笔记」聚合列表。"""
    _, doc = _ensure_pdf_file(db, current_user, file_id)
    rows = list_public_annotations_with_authors(db, doc=doc)
    out = []
    for ann, username in rows:
        out.append(
            {
                "id": ann.id,
                "user_id": ann.user_id,
                "username": username,
                "annotation_json": ann.annotation_json,
                "version": ann.version,
                "is_public": ann.is_public,
                "readonly": True,
                "is_author": ann.user_id == current_user.id,
            }
        )
    return out


@router.get("/{file_id}/annotations/by-user/{user_id}")
def annotations_by_user(file_id: int, user_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    _, doc = _ensure_pdf_file(db, current_user, file_id)
    rows = list_public_by_user(db, doc=doc, user_id=user_id)
    return [{"id": r.id, "annotation_json": r.annotation_json, "version": r.version, "readonly": True} for r in rows]


@router.post("/{file_id}/qa")
def pdf_qa(
    file_id: int,
    payload: PdfQaRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    file_record, _ = _ensure_pdf_file(db, current_user, file_id)
    try:
        return ask_in_pdf(
            db,
            file_record=file_record,
            question=payload.question,
            current_user=current_user,
            strict_mode=payload.strict_mode,
            top_k=payload.top_k,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{file_id}/attachments")
def attachments_list(file_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    _, doc = _ensure_pdf_file(db, current_user, file_id)
    rows = list_attachments(db, doc=doc)
    return [{"id": r.id, "file_id": r.file_id, "attachment_type": r.attachment_type, "title": r.title, "sort_order": r.sort_order} for r in rows]


@router.post("/{file_id}/attachments")
def attachments_create(
    file_id: int,
    payload: AttachmentCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _, doc = _ensure_pdf_file(db, current_user, file_id)
    row = add_attachment(
        db,
        doc=doc,
        file_id=payload.file_id,
        attachment_type=payload.attachment_type,
        title=payload.title,
        created_by=current_user.id,
    )
    return {"id": row.id, "file_id": row.file_id, "attachment_type": row.attachment_type, "title": row.title, "sort_order": row.sort_order}


@router.delete("/{file_id}/attachments/{attachment_id}")
def attachments_delete(
    file_id: int,
    attachment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _, _ = _ensure_pdf_file(db, current_user, file_id)
    row = db.query(DocumentAttachment).filter(DocumentAttachment.id == attachment_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="附件不存在")
    remove_attachment(db, attachment=row)
    return {"ok": True}
