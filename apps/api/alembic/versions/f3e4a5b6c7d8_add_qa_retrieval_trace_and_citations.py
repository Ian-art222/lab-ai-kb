"""add qa_retrieval_traces and qa_citations

Revision ID: f3e4a5b6c7d8
Revises: 01a2b3c4d5e6
Create Date: 2026-04-06

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "f3e4a5b6c7d8"
down_revision: Union[str, Sequence[str], None] = "01a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "qa_retrieval_traces",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("assistant_message_id", sa.Integer(), nullable=True),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("retrieval_mode", sa.String(length=40), nullable=True),
        sa.Column("fusion_method", sa.String(length=40), nullable=True),
        sa.Column("top_k", sa.Integer(), nullable=True),
        sa.Column("candidate_k", sa.Integer(), nullable=True),
        sa.Column("candidate_chunks", sa.Integer(), nullable=True),
        sa.Column("matched_chunks", sa.Integer(), nullable=True),
        sa.Column("selected_chunks", sa.Integer(), nullable=True),
        sa.Column("score_threshold_applied", sa.Float(), nullable=True),
        sa.Column("answer_source", sa.String(length=64), nullable=True),
        sa.Column("rerank_enabled", sa.Boolean(), nullable=True),
        sa.Column("rerank_applied", sa.Boolean(), nullable=True),
        sa.Column("rerank_model_name", sa.String(length=200), nullable=True),
        sa.Column("debug_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["assistant_message_id"], ["qa_messages.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["session_id"], ["qa_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_qa_retrieval_traces_assistant_message_id"),
        "qa_retrieval_traces",
        ["assistant_message_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_qa_retrieval_traces_session_id"), "qa_retrieval_traces", ["session_id"], unique=False
    )

    op.create_table(
        "qa_citations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("message_id", sa.Integer(), nullable=False),
        sa.Column("file_id", sa.Integer(), nullable=False),
        sa.Column("chunk_id", sa.Integer(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("section_title", sa.String(length=500), nullable=True),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("citation_order", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["message_id"], ["qa_messages.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_qa_citations_chunk_id"), "qa_citations", ["chunk_id"], unique=False)
    op.create_index(op.f("ix_qa_citations_file_id"), "qa_citations", ["file_id"], unique=False)
    op.create_index(op.f("ix_qa_citations_message_id"), "qa_citations", ["message_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_qa_citations_message_id"), table_name="qa_citations")
    op.drop_index(op.f("ix_qa_citations_file_id"), table_name="qa_citations")
    op.drop_index(op.f("ix_qa_citations_chunk_id"), table_name="qa_citations")
    op.drop_table("qa_citations")
    op.drop_index(op.f("ix_qa_retrieval_traces_session_id"), table_name="qa_retrieval_traces")
    op.drop_index(op.f("ix_qa_retrieval_traces_assistant_message_id"), table_name="qa_retrieval_traces")
    op.drop_table("qa_retrieval_traces")
