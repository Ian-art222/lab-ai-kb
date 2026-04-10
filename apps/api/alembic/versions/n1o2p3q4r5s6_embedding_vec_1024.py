"""embedding_vec vector(1536) -> vector(1024) for DashScope text-embedding-v3

Revision ID: n1o2p3q4r5s6
Revises: p1q2r3s4t5u6
Create Date: 2026-04-10

- Drops HNSW index on embedding_vec, drops column, re-adds vector(1024), recreates index.
- Does NOT transform old vectors: 1536-dim values are incompatible with 1024-dim space.
- After upgrade, run full re-embed: `python scripts/reindex_files.py --action reindex-all`
  (or per-file ingest with force_reindex) so embedding + embedding_vec are repopulated.

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "n1o2p3q4r5s6"
down_revision: Union[str, Sequence[str], None] = "p1q2r3s4t5u6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_INDEX_NAME = "ix_knowledge_chunks_embedding_vec_hnsw"
_HNSW_DEF = (
    f"CREATE INDEX IF NOT EXISTS {_INDEX_NAME} "
    "ON knowledge_chunks USING hnsw (embedding_vec vector_cosine_ops) "
    "WITH (m = 16, ef_construction = 64)"
)


def upgrade() -> None:
    op.execute(sa.text(f"DROP INDEX IF EXISTS {_INDEX_NAME}"))
    op.execute(sa.text("ALTER TABLE knowledge_chunks DROP COLUMN IF EXISTS embedding_vec"))
    op.execute(sa.text("ALTER TABLE knowledge_chunks ADD COLUMN embedding_vec vector(1024)"))
    op.execute(sa.text(_HNSW_DEF))


def downgrade() -> None:
    """Restore 1536-dim column and index. All embedding_vec data is lost (column recreated empty)."""
    op.execute(sa.text(f"DROP INDEX IF EXISTS {_INDEX_NAME}"))
    op.execute(sa.text("ALTER TABLE knowledge_chunks DROP COLUMN IF EXISTS embedding_vec"))
    op.execute(sa.text("ALTER TABLE knowledge_chunks ADD COLUMN embedding_vec vector(1536)"))
    op.execute(sa.text(_HNSW_DEF))
