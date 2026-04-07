from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
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
    # pgvector column (fixed dim in DB migration; NULL when embedding dim differs).
    embedding_vec: Mapped[list[float] | None] = mapped_column(Vector(1536), nullable=True)
    search_vector: Mapped[TSVECTOR | None] = mapped_column(
        TSVECTOR, nullable=True,
        comment="PostgreSQL full-text search vector (simple config, populated externally).",
    )
    chunk_kind: Mapped[str | None] = mapped_column(sa.String(20), nullable=True, index=True)
    parent_chunk_id: Mapped[int | None] = mapped_column(
        sa.ForeignKey("knowledge_chunks.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    metadata_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

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


class QARetrievalTrace(Base):
    """One row per /api/qa/ask attempt for analytics (success or failure)."""

    __tablename__ = "qa_retrieval_traces"

    id: Mapped[int] = mapped_column(sa.Integer, primary_key=True, index=True)
    session_id: Mapped[int] = mapped_column(
        sa.ForeignKey("qa_sessions.id", ondelete="CASCADE"), index=True, nullable=False
    )
    assistant_message_id: Mapped[int | None] = mapped_column(
        sa.ForeignKey("qa_messages.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    question: Mapped[str] = mapped_column(sa.Text, nullable=False)
    trace_id: Mapped[str | None] = mapped_column(sa.String(64), nullable=True, index=True)
    request_id: Mapped[str | None] = mapped_column(sa.String(64), nullable=True, index=True)
    retrieval_mode: Mapped[str | None] = mapped_column(sa.String(40), nullable=True)
    fusion_method: Mapped[str | None] = mapped_column(sa.String(40), nullable=True)
    top_k: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    candidate_k: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    candidate_chunks: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    matched_chunks: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    selected_chunks: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    score_threshold_applied: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    answer_source: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    rerank_enabled: Mapped[bool | None] = mapped_column(sa.Boolean, nullable=True)
    rerank_applied: Mapped[bool | None] = mapped_column(sa.Boolean, nullable=True)
    rerank_model_name: Mapped[str | None] = mapped_column(sa.String(200), nullable=True)
    is_abstained: Mapped[bool | None] = mapped_column(sa.Boolean, nullable=True)
    abstain_reason: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    model_name: Mapped[str | None] = mapped_column(sa.String(200), nullable=True)
    latency_ms: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    filters_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    evidence_bundles_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    token_usage_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    task_type: Mapped[str | None] = mapped_column(sa.String(50), nullable=True)
    tool_traces_json: Mapped[list | dict | None] = mapped_column(JSONB, nullable=True)
    workflow_steps_json: Mapped[list | dict | None] = mapped_column(JSONB, nullable=True)
    session_context_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    debug_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime, default=datetime.utcnow, nullable=False
    )


class QACitation(Base):
    """Normalized citations for an assistant answer (optional; empty on errors)."""

    __tablename__ = "qa_citations"

    id: Mapped[int] = mapped_column(sa.Integer, primary_key=True, index=True)
    message_id: Mapped[int] = mapped_column(
        sa.ForeignKey("qa_messages.id", ondelete="CASCADE"), index=True, nullable=False
    )
    file_id: Mapped[int] = mapped_column(sa.Integer, nullable=False, index=True)
    chunk_id: Mapped[int] = mapped_column(sa.Integer, nullable=False, index=True)
    chunk_index: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    page_number: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    section_title: Mapped[str | None] = mapped_column(sa.String(500), nullable=True)
    score: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    citation_order: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)

