from __future__ import annotations

from datetime import datetime

from fastapi import BackgroundTasks
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.knowledge import KnowledgeChunk
from app.models.pdf_literature import PdfDocument, PdfTranslationTask
from app.models.system_setting import SystemSetting
from app.core.config import settings as app_settings
from app.services.model_service import chat_completion


ACTIVE_STATUSES = {"pending", "running"}


def get_latest_task(db: Session, *, doc_id: int, target_language: str) -> PdfTranslationTask | None:
    return (
        db.query(PdfTranslationTask)
        .filter(
            PdfTranslationTask.doc_id == doc_id,
            PdfTranslationTask.target_language == target_language,
        )
        .first()
    )


def request_translation(
    db: Session,
    *,
    doc: PdfDocument,
    target_language: str,
    source_language: str | None,
    requested_by: int | None,
    background_tasks: BackgroundTasks,
) -> PdfTranslationTask:
    lang = (target_language or "zh-CN").strip()
    existing = get_latest_task(db, doc_id=doc.id, target_language=lang)
    if existing and existing.status in ACTIVE_STATUSES | {"completed"}:
        return existing

    if existing:
        existing.source_language = source_language
        existing.status = "pending"
        existing.progress = 0
        existing.error_message = None
        existing.requested_by = requested_by
        existing.translated_structured_json = None
        db.commit()
        db.refresh(existing)
        background_tasks.add_task(_run_translation_task, existing.id)
        return existing

    task = PdfTranslationTask(
        doc_id=doc.id,
        source_language=source_language,
        target_language=lang,
        status="pending",
        progress=0,
        requested_by=requested_by,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    background_tasks.add_task(_run_translation_task, task.id)
    return task


def _run_translation_task(task_id: int) -> None:
    db = SessionLocal()
    try:
        task = db.query(PdfTranslationTask).filter(PdfTranslationTask.id == task_id).first()
        if not task:
            return
        doc = db.query(PdfDocument).filter(PdfDocument.id == task.doc_id).first()
        if not doc:
            task.status = "failed"
            task.error_message = "文献不存在"
            db.commit()
            return

        sys_settings = db.query(SystemSetting).filter(SystemSetting.id == 1).first()
        if not sys_settings or not (
            sys_settings.llm_api_base and sys_settings.llm_api_key and sys_settings.llm_model
        ):
            task.status = "failed"
            task.error_message = "LLM 配置不完整"
            db.commit()
            return

        chunks = (
            db.query(KnowledgeChunk)
            .filter(
                KnowledgeChunk.file_id == doc.file_id,
                ((KnowledgeChunk.chunk_kind == "child") | (KnowledgeChunk.chunk_kind.is_(None))),
            )
            .order_by(KnowledgeChunk.page_number.asc().nullsfirst(), KnowledgeChunk.chunk_index.asc())
            .all()
        )
        if not chunks:
            task.status = "failed"
            task.error_message = "原文索引不存在，请先完成索引"
            db.commit()
            return

        task.status = "running"
        task.progress = 1
        task.provider_name = sys_settings.llm_provider
        db.commit()

        total = len(chunks)
        items: list[dict] = []
        for idx, ch in enumerate(chunks, start=1):
            translated = chat_completion(
                provider=sys_settings.llm_provider,
                api_base=sys_settings.llm_api_base,
                api_key=sys_settings.llm_api_key,
                model=sys_settings.llm_model,
                timeout=app_settings.pdf_translation_llm_timeout,
                messages=[
                    {
                        "role": "system",
                        "content": "你是学术翻译助手。保持术语准确，输出纯译文，不要解释。",
                    },
                    {
                        "role": "user",
                        "content": f"把下面内容翻译为 {task.target_language}：\n\n{ch.content}",
                    },
                ],
            )
            items.append(
                {
                    "chunk_id": ch.id,
                    "chunk_index": ch.chunk_index,
                    "page_number": ch.page_number,
                    "source": ch.content,
                    "translated": translated,
                }
            )
            task.progress = int(idx * 100 / total)
            db.commit()

        task.translated_structured_json = {
            "file_id": doc.file_id,
            "target_language": task.target_language,
            "items": items,
        }
        task.status = "completed"
        task.progress = 100
        task.completed_at = datetime.utcnow()
        doc.translated_available = True
        db.commit()
    except Exception as exc:  # noqa: BLE001
        task = db.query(PdfTranslationTask).filter(PdfTranslationTask.id == task_id).first()
        if task:
            task.status = "failed"
            task.error_message = str(exc)
            # 进入循环前会把 progress 置为 1；若首轮 LLM 即失败，易误判为「刚开始翻译」
            if (task.progress or 0) <= 1:
                task.progress = 0
            db.commit()
    finally:
        db.close()
