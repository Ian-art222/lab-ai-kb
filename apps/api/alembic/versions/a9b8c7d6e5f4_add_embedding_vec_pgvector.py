"""add knowledge_chunks.embedding_vec + pgvector HNSW index

Revision ID: a9b8c7d6e5f4
Revises: f3e4a5b6c7d8
Create Date: 2026-04-06

Fixed 1536 dimensions (common ada-002 / text-embedding-3-small size). Other embedding sizes keep embedding_vec NULL.

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "a9b8c7d6e5f4"
down_revision: Union[str, Sequence[str], None] = "f3e4a5b6c7d8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))
    op.execute(
        sa.text("ALTER TABLE knowledge_chunks ADD COLUMN IF NOT EXISTS embedding_vec vector(1536)")
    )
    op.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_knowledge_chunks_embedding_vec_hnsw "
            "ON knowledge_chunks USING hnsw (embedding_vec vector_cosine_ops) "
            "WITH (m = 16, ef_construction = 64)"
        )
    )


def downgrade() -> None:
    op.execute(sa.text("DROP INDEX IF EXISTS ix_knowledge_chunks_embedding_vec_hnsw"))
    op.execute(sa.text("ALTER TABLE knowledge_chunks DROP COLUMN IF EXISTS embedding_vec"))
