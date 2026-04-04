from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"
    __table_args__ = (
        sa.UniqueConstraint("file_id", "chunk_index", name="uq_knowledge_chunks_file_chunk"),
    )

    id: Mapped[int] = mapped_column(sa.Integer, primary_key=True, index=True)
    file_id: Mapped[int] = mapped_column(
        sa.ForeignKey("files.id", ondelete="CASCADE"), index=True
    )
    folder_id: Mapped[int | None] = mapped_column(
        sa.ForeignKey("folders.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    chunk_index: Mapped[int] = mapped_column(sa.Integer, nullable=False, index=True)
    content: Mapped[str] = mapped_column(sa.Text, nullable=False)
    section_title: Mapped[str | None] = mapped_column(sa.String(200), nullable=True)
    page_number: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    token_count: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    # Store embedding as Postgres float array for MVP compatibility.
    embedding: Mapped[list[float] | None] = mapped_column(sa.ARRAY(sa.Float), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime, default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )


class QASession(Base):
    __tablename__ = "qa_sessions"

    id: Mapped[int] = mapped_column(sa.Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str | None] = mapped_column(sa.String(200), nullable=True)
    scope_type: Mapped[str] = mapped_column(sa.String(20), nullable=False, default="all")
    folder_id: Mapped[int | None] = mapped_column(
        sa.ForeignKey("folders.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime, default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )


class QAMessage(Base):
    __tablename__ = "qa_messages"

    id: Mapped[int] = mapped_column(sa.Integer, primary_key=True, index=True)
    session_id: Mapped[int] = mapped_column(
        sa.ForeignKey("qa_sessions.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(sa.String(20), nullable=False, index=True)
    content: Mapped[str] = mapped_column(sa.Text, nullable=False)
    references_json: Mapped[dict | list | None] = mapped_column(sa.JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime, default=datetime.utcnow, nullable=False
    )

