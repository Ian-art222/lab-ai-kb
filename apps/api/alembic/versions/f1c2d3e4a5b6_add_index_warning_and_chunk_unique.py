"""add index_warning and chunk unique constraint

Revision ID: f1c2d3e4a5b6
Revises: d8a7c1e4f9b2
Create Date: 2026-04-03 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f1c2d3e4a5b6"
down_revision: Union[str, Sequence[str], None] = "d8a7c1e4f9b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("files", sa.Column("index_warning", sa.Text(), nullable=True))

    op.execute(
        """
        DELETE FROM knowledge_chunks
        WHERE id IN (
            SELECT id FROM (
                SELECT
                    id,
                    ROW_NUMBER() OVER (
                        PARTITION BY file_id, chunk_index
                        ORDER BY id ASC
                    ) AS rn
                FROM knowledge_chunks
            ) ranked
            WHERE ranked.rn > 1
        )
        """
    )
    op.create_unique_constraint(
        "uq_knowledge_chunks_file_chunk",
        "knowledge_chunks",
        ["file_id", "chunk_index"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_knowledge_chunks_file_chunk",
        "knowledge_chunks",
        type_="unique",
    )
    op.drop_column("files", "index_warning")
