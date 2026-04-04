from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from PyPDF2 import PdfReader
from sqlalchemy.orm import Session
from docx import Document

from app.core.config import settings as app_settings
from app.models.file_record import FileRecord
from app.models.knowledge import KnowledgeChunk
from app.models.system_setting import SystemSetting
from app.services.model_service import embed_texts
from app.services.settings_service import (
    build_embedding_index_standard,
    get_effective_embedding_batch_size,
)

CHUNK_SIZE = 1000
CHUNK_OVERLAP = 150
MIN_CHUNK_CHARS = 80
MIN_MEANINGFUL_TEXT_CHARS = 5
MAX_INDEX_TEXT_CHARS = 200000

logger = logging.getLogger(__name__)


def _resolve_file_path(file_record: FileRecord) -> Path:
    storage_path = file_record.storage_path or file_record.file_name
    return Path(app_settings.upload_dir) / storage_path


def _extract_text(file_record: FileRecord, file_path: Path) -> str:
    file_type = (file_record.file_type or "").lower()

    if file_type in {"txt", "md"}:
        return file_path.read_text(encoding="utf-8")
    if file_type == "pdf":
        reader = PdfReader(str(file_path))
        pages = [(page.extract_text() or "").strip() for page in reader.pages]
        return "\n\n".join([page for page in pages if page])
    if file_type == "docx":
        document = Document(str(file_path))
        paragraphs = [paragraph.text.strip() for paragraph in document.paragraphs]
        return "\n".join([paragraph for paragraph in paragraphs if paragraph])

    raise ValueError(f"暂不支持该文件类型索引：{file_type or 'unknown'}")


def _extract_segments(file_record: FileRecord, file_path: Path) -> list[dict]:
    file_type = (file_record.file_type or "").lower()

    if file_type in {"txt", "md"}:
        return [{"text": file_path.read_text(encoding="utf-8"), "page_number": None}]
    if file_type == "pdf":
        reader = PdfReader(str(file_path))
        segments: list[dict] = []
        for index, page in enumerate(reader.pages):
            page_text = (page.extract_text() or "").strip()
            if page_text:
                segments.append({"text": page_text, "page_number": index + 1})
        return segments
    if file_type == "docx":
        document = Document(str(file_path))
        paragraphs = [paragraph.text.strip() for paragraph in document.paragraphs if paragraph.text.strip()]
        return [{"text": "\n".join(paragraphs), "page_number": None}]

    raise ValueError(f"暂不支持该文件类型索引：{file_type or 'unknown'}")


def _guess_section_title(text: str) -> str | None:
    for line in text.splitlines():
        candidate = line.strip().strip("#").strip()
        if 4 <= len(candidate) <= 80:
            return candidate
    return None


def _limit_segments(segments: list[dict]) -> tuple[list[dict], bool]:
    limited: list[dict] = []
    total = 0
    truncated = False
    for segment in segments:
        content = segment["text"].strip()
        if not content:
            continue
        remaining = MAX_INDEX_TEXT_CHARS - total
        if remaining <= 0:
            truncated = True
            break
        if len(content) > remaining:
            limited.append(
                {
                    "text": content[:remaining],
                    "page_number": segment.get("page_number"),
                }
            )
            truncated = True
            break
        limited.append({"text": content, "page_number": segment.get("page_number")})
        total += len(content)
    return limited, truncated


def _chunk_text(text: str, *, page_number: int | None = None) -> tuple[list[dict], str | None]:
    normalized = text.strip()
    if not normalized:
        return [], None
    if len(normalized) < MIN_MEANINGFUL_TEXT_CHARS:
        return [], "文本内容过短，无法建立稳定索引"

    chunks: list[dict] = []
    warning: str | None = None
    if len(normalized) < MIN_CHUNK_CHARS:
        return (
            [
                {
                    "content": normalized,
                    "page_number": page_number,
                    "section_title": _guess_section_title(normalized),
                }
            ],
            "文本较短，检索效果可能有限",
        )
    start = 0
    text_length = len(normalized)

    while start < text_length:
        end = min(start + CHUNK_SIZE, text_length)
        chunk = normalized[start:end].strip()
        if chunk and len(chunk) >= MIN_CHUNK_CHARS:
            chunks.append(
                {
                    "content": chunk,
                    "page_number": page_number,
                    "section_title": _guess_section_title(chunk),
                }
            )
        if end >= text_length:
            break
        start = max(0, end - CHUNK_OVERLAP)

    return chunks, warning


def _mark_index_success(
    db: Session,
    *,
    file_record: FileRecord,
    extracted_text_length: int,
    warnings: list[str],
    indexed_at: datetime,
    index_embedding_provider: str | None,
    index_embedding_model: str | None,
    index_embedding_dimension: int | None,
) -> FileRecord:
    file_record.extracted_text_length = extracted_text_length
    file_record.index_status = "indexed"
    file_record.indexed_at = indexed_at
    file_record.index_error = None
    file_record.index_warning = "；".join(warnings) if warnings else None
    file_record.index_embedding_provider = index_embedding_provider
    file_record.index_embedding_model = index_embedding_model
    file_record.index_embedding_dimension = index_embedding_dimension
    db.commit()
    db.refresh(file_record)
    return file_record


def _mark_index_failure(
    db: Session,
    *,
    file_id: int,
    error_message: str,
) -> FileRecord:
    db.rollback()
    db.query(KnowledgeChunk).filter(KnowledgeChunk.file_id == file_id).delete()
    file_record = db.query(FileRecord).filter(FileRecord.id == file_id).first()
    if file_record is None:
        raise RuntimeError(error_message)
    file_record.index_status = "failed"
    file_record.indexed_at = None
    file_record.index_error = error_message
    file_record.index_warning = None
    file_record.index_embedding_provider = None
    file_record.index_embedding_model = None
    file_record.index_embedding_dimension = None
    db.commit()
    db.refresh(file_record)
    return file_record


def ingest_file(db: Session, file_record: FileRecord) -> FileRecord:
    return ingest_file_job(db, file_record, prepare_indexing=True)


def ingest_file_job(
    db: Session,
    file_record: FileRecord,
    *,
    prepare_indexing: bool,
) -> FileRecord:
    if prepare_indexing:
        file_record.index_status = "indexing"
        file_record.index_error = None
        file_record.index_warning = None
        file_record.indexed_at = None
        file_record.index_embedding_provider = None
        file_record.index_embedding_model = None
        file_record.index_embedding_dimension = None
        db.commit()
        db.refresh(file_record)
    file_path = _resolve_file_path(file_record)

    try:
        if not file_path.exists():
            raise FileNotFoundError("物理文件不存在，无法建立索引")
        if file_record.file_size == 0:
            raise ValueError("文件为空，无法建立索引")

        text = _extract_text(file_record, file_path)
        segments = _extract_segments(file_record, file_path)
        if not text.strip():
            raise ValueError("文件解析完成，但未提取到可用文本内容")

        limited_segments, truncated = _limit_segments(segments)
        warnings: list[str] = []
        if truncated:
            warnings.append("文件文本较长，本次仅截取前 200000 个字符建立索引")

        chunks: list[dict] = []
        for segment in limited_segments:
            segment_chunks, segment_warning = _chunk_text(
                segment["text"],
                page_number=segment.get("page_number"),
            )
            chunks.extend(segment_chunks)
            if segment_warning and segment_warning not in warnings:
                warnings.append(segment_warning)
        if not chunks:
            raise ValueError("文本内容不足以形成可用索引")

        logger.info(
            "Start ingest file_id=%s chunk_count=%s extracted_text_length=%s",
            file_record.id,
            len(chunks),
            len(text),
        )

        db.query(KnowledgeChunk).filter(KnowledgeChunk.file_id == file_record.id).delete()

        settings = db.query(SystemSetting).filter(SystemSetting.id == 1).first()
        embeddings: list[list[float] | None] = [None] * len(chunks)
        embedding_warning: str | None = None
        index_embedding_provider: str | None = None
        index_embedding_model: str | None = None
        index_embedding_dimension: int | None = None
        if (
            settings
            and settings.embedding_provider
            and settings.embedding_api_base
            and settings.embedding_api_key
            and settings.embedding_model
        ):
            current_index_standard = build_embedding_index_standard(
                embedding_provider=settings.embedding_provider,
                embedding_model=settings.embedding_model,
            )
            effective_batch = get_effective_embedding_batch_size(
                embedding_provider_raw=settings.embedding_provider,
                db_batch_size=settings.embedding_batch_size,
            )
            total_batches = (len(chunks) + effective_batch - 1) // effective_batch
            logger.info(
                "Embedding ingest file_id=%s provider=%s model=%s index_standard=%s chunk_count=%s total_batches=%s "
                "effective_batch_size=%s db_embedding_batch_size=%s",
                file_record.id,
                settings.embedding_provider,
                settings.embedding_model,
                current_index_standard,
                len(chunks),
                total_batches,
                effective_batch,
                settings.embedding_batch_size,
            )
            embeddings = embed_texts(
                provider=settings.embedding_provider,
                api_base=settings.embedding_api_base,
                api_key=settings.embedding_api_key,
                model=settings.embedding_model,
                inputs=[chunk["content"] for chunk in chunks],
                embedding_batch_size_from_db=settings.embedding_batch_size,
            )
            if embeddings and embeddings[0]:
                index_embedding_provider = settings.embedding_provider
                index_embedding_model = settings.embedding_model
                index_embedding_dimension = len(embeddings[0])
            logger.info(
                "Embedding ingest completed file_id=%s embedding_count=%s index_standard=%s embedding_dim=%s",
                file_record.id,
                len(embeddings),
                current_index_standard,
                index_embedding_dimension,
            )
        else:
            embedding_warning = "Embedding 配置不完整，本次仅完成文本分块索引"
            warnings.append(embedding_warning)

        now = datetime.utcnow()
        for idx, chunk in enumerate(chunks):
            db.add(
                KnowledgeChunk(
                    file_id=file_record.id,
                    folder_id=file_record.folder_id,
                    chunk_index=idx,
                    content=chunk["content"],
                    section_title=chunk["section_title"],
                    page_number=chunk["page_number"],
                    token_count=len(chunk["content"]),
                    embedding=embeddings[idx],
                    created_at=now,
                    updated_at=now,
                )
            )

        return _mark_index_success(
            db,
            file_record=file_record,
            extracted_text_length=len(text),
            warnings=warnings,
            indexed_at=now,
            index_embedding_provider=index_embedding_provider,
            index_embedding_model=index_embedding_model,
            index_embedding_dimension=index_embedding_dimension,
        )
    except Exception as exc:
        logger.exception(
            "Ingest failed file_id=%s content_hash=%s error=%s",
            file_record.id,
            file_record.content_hash,
            exc,
        )
        return _mark_index_failure(
            db,
            file_id=file_record.id,
            error_message=str(exc),
        )
