"""add rag index fields and qa tables

This migration extends `files` with knowledge indexing status fields,
and adds tables for knowledge chunks and qa sessions/messages.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b9b3e7a8c1d4"
down_revision: Union[str, Sequence[str], None] = "8b7a6c5d4e3f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1) extend files table with index status columns
    op.add_column(
        "files",
        sa.Column(
            "index_status",
            sa.String(length=20),
            nullable=False,
            server_default="pending",
        ),
    )
    op.add_column("files", sa.Column("indexed_at", sa.DateTime(), nullable=True))
    op.add_column("files", sa.Column("index_error", sa.Text(), nullable=True))
    op.add_column(
        "files", sa.Column("extracted_text_length", sa.Integer(), nullable=True)
    )
    op.add_column("files", sa.Column("content_hash", sa.String(length=64), nullable=True))
    op.add_column("files", sa.Column("mime_type", sa.String(length=100), nullable=True))

    # 2) knowledge chunks table
    op.create_table(
        "knowledge_chunks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "file_id",
            sa.Integer(),
            sa.ForeignKey("files.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "folder_id",
            sa.Integer(),
            sa.ForeignKey("folders.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("section_title", sa.String(length=200), nullable=True),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("token_count", sa.Integer(), nullable=True),
        sa.Column("embedding", sa.ARRAY(sa.Float()), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_knowledge_chunks_file_id", "knowledge_chunks", ["file_id"], unique=False)
    op.create_index("ix_knowledge_chunks_folder_id", "knowledge_chunks", ["folder_id"], unique=False)
    op.create_index("ix_knowledge_chunks_chunk_index", "knowledge_chunks", ["chunk_index"], unique=False)

    # 3) qa sessions
    op.create_table(
        "qa_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(length=200), nullable=True),
        sa.Column("scope_type", sa.String(length=20), nullable=False, server_default="all"),
        sa.Column(
            "folder_id",
            sa.Integer(),
            sa.ForeignKey("folders.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_qa_sessions_user_id", "qa_sessions", ["user_id"], unique=False)
    op.create_index("ix_qa_sessions_folder_id", "qa_sessions", ["folder_id"], unique=False)

    # 4) qa messages
    op.create_table(
        "qa_messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "session_id",
            sa.Integer(),
            sa.ForeignKey("qa_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("references_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_qa_messages_session_id", "qa_messages", ["session_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_qa_messages_session_id", table_name="qa_messages")
    op.drop_table("qa_messages")
    op.drop_index("ix_qa_sessions_folder_id", table_name="qa_sessions")
    op.drop_index("ix_qa_sessions_user_id", table_name="qa_sessions")
    op.drop_table("qa_sessions")

    op.drop_index("ix_knowledge_chunks_chunk_index", table_name="knowledge_chunks")
    op.drop_index("ix_knowledge_chunks_folder_id", table_name="knowledge_chunks")
    op.drop_index("ix_knowledge_chunks_file_id", table_name="knowledge_chunks")
    op.drop_table("knowledge_chunks")

    op.drop_column("files", "mime_type")
    op.drop_column("files", "content_hash")
    op.drop_column("files", "extracted_text_length")
    op.drop_column("files", "index_error")
    op.drop_column("files", "indexed_at")
    op.drop_column("files", "index_status")

