"""add nullable embedding_batch_size to system_settings

Revision ID: f7e8d9c0b1a2
Revises: c9d8e7f6a5b4
Create Date: 2026-04-04

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f7e8d9c0b1a2"
down_revision: Union[str, Sequence[str], None] = "c9d8e7f6a5b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "system_settings",
        sa.Column("embedding_batch_size", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("system_settings", "embedding_batch_size")
