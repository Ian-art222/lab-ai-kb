"""add storage_path and file_size to files

Revision ID: c4d8e1f2a7b9
Revises: b9b3e7a8c1d4
Create Date: 2026-04-03 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c4d8e1f2a7b9"
down_revision: Union[str, Sequence[str], None] = "b9b3e7a8c1d4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "files",
        sa.Column("storage_path", sa.String(length=500), nullable=True),
    )
    op.add_column(
        "files",
        sa.Column("file_size", sa.Integer(), nullable=True),
    )

    # Minimal compatibility for existing rows:
    # fall back to the legacy file_name as storage path until upload logic is upgraded.
    op.execute("UPDATE files SET storage_path = file_name WHERE storage_path IS NULL")


def downgrade() -> None:
    op.drop_column("files", "file_size")
    op.drop_column("files", "storage_path")
