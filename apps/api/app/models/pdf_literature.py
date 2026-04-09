"""PDF 文献扩展：与 files 1:1 关联，翻译任务、批注（预留）、附件。"""

from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PdfDocument(Base):
    __tablename__ = "pdf_documents"
    __table_args__ = (sa.UniqueConstraint("file_id", name="uq_pdf_documents_file_id"),)

    id: Mapped[int] = mapped_column(sa.Integer, primary_key=True, index=True)
    file_id: Mapped[int] = mapped_column(
        sa.ForeignKey("files.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str | None] = mapped_column(sa.String(512), nullable=True)
    authors_json: Mapped[list | dict | None] = mapped_column(JSONB, nullable=True)
    journal: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)
    publication_year: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    doi: Mapped[str | None] = mapped_column(sa.String(256), nullable=True)
    abstract_text: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    language: Mapped[str | None] = mapped_column(sa.String(32), nullable=True)
    page_count: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)

    parse_status: Mapped[str] = mapped_column(
        sa.String(32), nullable=False, default="pending"
    )  # pending | parsing | completed | failed
    parse_progress: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    parse_error: Mapped[str | None] = mapped_column(sa.Text, nullable=True)

    index_status: Mapped[str] = mapped_column(
        sa.String(32), nullable=False, default="pending"
    )  # pending | indexing | indexed | failed — 与 files.index_status 同步展示
    index_progress: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    index_error: Mapped[str | None] = mapped_column(sa.Text, nullable=True)

    translated_available: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=False)

    created_by: Mapped[int | None] = mapped_column(
        sa.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime, default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )


class PdfTranslationTask(Base):
    __tablename__ = "pdf_translation_tasks"
    __table_args__ = (
        sa.UniqueConstraint("doc_id", "target_language", name="uq_pdf_translation_doc_lang"),
    )

    id: Mapped[int] = mapped_column(sa.Integer, primary_key=True, index=True)
    doc_id: Mapped[int] = mapped_column(
        sa.ForeignKey("pdf_documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_language: Mapped[str | None] = mapped_column(sa.String(32), nullable=True)
    target_language: Mapped[str] = mapped_column(sa.String(32), nullable=False)

    status: Mapped[str] = mapped_column(
        sa.String(32), nullable=False, default="pending"
    )  # pending | running | completed | failed
    progress: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)

    provider_name: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    provider_task_id: Mapped[str | None] = mapped_column(sa.String(128), nullable=True)

    translated_structured_json: Mapped[dict | list | None] = mapped_column(JSONB, nullable=True)
    translated_artifact_path: Mapped[str | None] = mapped_column(sa.String(500), nullable=True)

    source_hash: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(sa.Text, nullable=True)

    requested_by: Mapped[int | None] = mapped_column(
        sa.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(sa.DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime, default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )


class PdfAnnotation(Base):
    __tablename__ = "pdf_annotations"

    id: Mapped[int] = mapped_column(sa.Integer, primary_key=True, index=True)
    doc_id: Mapped[int] = mapped_column(
        sa.ForeignKey("pdf_documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[int] = mapped_column(
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    is_public: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=False)
    annotation_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    version: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime, default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )


class DocumentAttachment(Base):
    __tablename__ = "document_attachments"
    __table_args__ = (
        sa.UniqueConstraint("doc_id", "file_id", name="uq_document_attachment_doc_file"),
    )

    id: Mapped[int] = mapped_column(sa.Integer, primary_key=True, index=True)
    doc_id: Mapped[int] = mapped_column(
        sa.ForeignKey("pdf_documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    file_id: Mapped[int] = mapped_column(
        sa.ForeignKey("files.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    attachment_type: Mapped[str] = mapped_column(sa.String(64), nullable=False, default="supplement")
    title: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)
    sort_order: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    created_by: Mapped[int | None] = mapped_column(
        sa.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime, default=datetime.utcnow, nullable=False
    )
