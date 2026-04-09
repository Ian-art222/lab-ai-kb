from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.permissions import user_may_access_file_record
from app.db.session import get_db
from app.models.file_record import FileRecord
from app.models.pdf_literature import DocumentAttachment, PdfAnnotation
from app.models.system_setting import SystemSetting
from app.models.user import User
from app.services.model_service import chat_completion
from app.services.pdf_annotation_service import (
    create_annotation,
    delete_annotation,
    list_my_annotations,
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
from app.services.pdf_translation_service import get_latest_task, request_translation

router = APIRouter(prefix="/api/pdf-documents", tags=["pdf-documents"])


class TranslateRequest(BaseModel):
    target_language: str = "zh-CN"
    source_language: str | None = None


class SelectionTranslateRequest(BaseModel):
    text: str
    target_language: str = "zh-CN"


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
            "translated_available": doc.translated_available,
        },
        "file": {
            "id": file_record.id,
            "file_name": file_record.file_name,
            "file_type": file_record.file_type,
            "mime_type": file_record.mime_type,
            "index_status": file_record.index_status,
            "can_download": True,
        },
    }


@router.post("/{file_id}/translate")
def trigger_translate(
    file_id: int,
    payload: TranslateRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _, doc = _ensure_pdf_file(db, current_user, file_id)
    task = request_translation(
        db,
        doc=doc,
        target_language=payload.target_language,
        source_language=payload.source_language,
        requested_by=current_user.id,
        background_tasks=background_tasks,
    )
    return {"task_id": task.id, "status": task.status, "progress": task.progress, "target_language": task.target_language}


@router.get("/{file_id}/translation-status")
def translation_status(
    file_id: int,
    target_language: str = "zh-CN",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _, doc = _ensure_pdf_file(db, current_user, file_id)
    task = get_latest_task(db, doc_id=doc.id, target_language=target_language)
    if not task:
        return {"status": "not_started", "progress": 0}
    return {"task_id": task.id, "status": task.status, "progress": task.progress, "error_message": task.error_message}


@router.get("/{file_id}/translation-content")
def translation_content(
    file_id: int,
    target_language: str = "zh-CN",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _, doc = _ensure_pdf_file(db, current_user, file_id)
    task = get_latest_task(db, doc_id=doc.id, target_language=target_language)
    if not task:
        raise HTTPException(status_code=404, detail="翻译任务不存在")
    return {
        "status": task.status,
        "progress": task.progress,
        "content": task.translated_structured_json,
        "error_message": task.error_message,
    }


@router.get("/{file_id}/download")
def document_download(
    file_id: int,
    include_original: bool = True,
    include_translation: bool = False,
    target_language: str = "zh-CN",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    file_record, doc = _ensure_pdf_file(db, current_user, file_id)
    task = get_latest_task(db, doc_id=doc.id, target_language=target_language)
    return build_download_response(
        file_record=file_record,
        translation_task=task,
        include_original=include_original,
        include_translation=include_translation,
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


@router.get("/{file_id}/annotations/by-user/{user_id}")
def annotations_by_user(file_id: int, user_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    _, doc = _ensure_pdf_file(db, current_user, file_id)
    rows = list_public_by_user(db, doc=doc, user_id=user_id)
    return [{"id": r.id, "annotation_json": r.annotation_json, "version": r.version, "readonly": True} for r in rows]


@router.post("/{file_id}/selection-translate")
def selection_translate(
    file_id: int,
    payload: SelectionTranslateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _, _ = _ensure_pdf_file(db, current_user, file_id)
    settings = db.query(SystemSetting).filter(SystemSetting.id == 1).first()
    if not settings:
        raise HTTPException(status_code=400, detail="系统设置不存在")
    translated = chat_completion(
        provider=settings.llm_provider,
        api_base=settings.llm_api_base,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        messages=[
            {"role": "system", "content": "你是术语准确的学术翻译助手，仅输出译文。"},
            {"role": "user", "content": f"翻译为 {payload.target_language}:\n\n{payload.text}"},
        ],
    )
    return {"translated": translated, "target_language": payload.target_language}


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
