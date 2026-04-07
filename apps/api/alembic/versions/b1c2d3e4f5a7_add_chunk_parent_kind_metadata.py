"""add chunk_kind, parent_chunk_id, metadata_json to knowledge_chunks

Revision ID: b1c2d3e4f5a7
Revises: a9b8c7d6e5f4
Create Date: 2026-04-06

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "b1c2d3e4f5a7"
down_revision: Union[str, Sequence[str], None] = "a9b8c7d6e5f4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("knowledge_chunks", sa.Column("chunk_kind", sa.String(length=20), nullable=True))
    op.add_column(
        "knowledge_chunks",
        sa.Column("parent_chunk_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "knowledge_chunks",
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.create_foreign_key(
        "fk_knowledge_chunks_parent_chunk_id",
        "knowledge_chunks",
        "knowledge_chunks",
        ["parent_chunk_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        op.f("ix_knowledge_chunks_chunk_kind"), "knowledge_chunks", ["chunk_kind"], unique=False
    )
    op.create_index(
        op.f("ix_knowledge_chunks_parent_chunk_id"),
        "knowledge_chunks",
        ["parent_chunk_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_knowledge_chunks_parent_chunk_id"), table_name="knowledge_chunks")
    op.drop_index(op.f("ix_knowledge_chunks_chunk_kind"), table_name="knowledge_chunks")
    op.drop_constraint("fk_knowledge_chunks_parent_chunk_id", "knowledge_chunks", type_="foreignkey")
    op.drop_column("knowledge_chunks", "metadata_json")
    op.drop_column("knowledge_chunks", "parent_chunk_id")
    op.drop_column("knowledge_chunks", "chunk_kind")
