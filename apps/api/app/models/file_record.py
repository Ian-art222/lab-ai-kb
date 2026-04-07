from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class FileRecord(Base):
    __tablename__ = "files"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_type: Mapped[str] = mapped_column(String(50), nullable=False)
    uploader: Mapped[str] = mapped_column(String(50), nullable=False)
    upload_time: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    folder_id: Mapped[int | None] = mapped_column(
        ForeignKey("folders.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # Knowledge index status (used by RAG QA)
    index_status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    index_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    index_warning: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    pipeline_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    index_embedding_provider: Mapped[str | None] = mapped_column(String(50), nullable=True)
    index_embedding_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    index_embedding_dimension: Mapped[int | None] = mapped_column(Integer, nullable=True)
    extracted_text_length: Mapped[int | None] = mapped_column(Integer, nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # Temporary nullable for backward compatibility until upload logic writes it.
    storage_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    file_size: Mapped[int | None] = mapped_column(Integer, nullable=True)