"""add last qa status fields

Revision ID: a7b8c9d0e1f2
Revises: f1c2d3e4a5b6
Create Date: 2026-04-04 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a7b8c9d0e1f2"
down_revision: Union[str, Sequence[str], None] = "f1c2d3e4a5b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("system_settings", sa.Column("last_qa_success", sa.Boolean(), nullable=True))
    op.add_column("system_settings", sa.Column("last_qa_at", sa.DateTime(), nullable=True))
    op.add_column("system_settings", sa.Column("last_qa_error", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("system_settings", "last_qa_error")
    op.drop_column("system_settings", "last_qa_at")
    op.drop_column("system_settings", "last_qa_success")
