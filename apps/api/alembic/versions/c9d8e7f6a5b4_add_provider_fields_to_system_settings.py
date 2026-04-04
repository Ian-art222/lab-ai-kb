"""add provider fields to system settings

Revision ID: c9d8e7f6a5b4
Revises: b1c2d3e4f5a6
Create Date: 2026-04-04 10:30:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c9d8e7f6a5b4"
down_revision: Union[str, Sequence[str], None] = "b1c2d3e4f5a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "system_settings",
        sa.Column("llm_provider", sa.String(length=50), nullable=False, server_default="openai_compatible"),
    )
    op.add_column(
        "system_settings",
        sa.Column(
            "embedding_provider",
            sa.String(length=50),
            nullable=False,
            server_default="openai_compatible",
        ),
    )
    op.alter_column("system_settings", "llm_provider", server_default=None)
    op.alter_column("system_settings", "embedding_provider", server_default=None)


def downgrade() -> None:
    op.drop_column("system_settings", "embedding_provider")
    op.drop_column("system_settings", "llm_provider")
