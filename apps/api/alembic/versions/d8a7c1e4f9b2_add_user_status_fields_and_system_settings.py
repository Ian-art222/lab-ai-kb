"""add user status fields and system settings

Revision ID: d8a7c1e4f9b2
Revises: c4d8e1f2a7b9
Create Date: 2026-04-03 00:00:00.000000
"""

from datetime import datetime
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d8a7c1e4f9b2"
down_revision: Union[str, Sequence[str], None] = "c4d8e1f2a7b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        "users",
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("last_login_at", sa.DateTime(), nullable=True),
    )

    now = datetime.utcnow()
    op.execute(
        sa.text("UPDATE users SET updated_at = :now WHERE updated_at IS NULL").bindparams(
            now=now
        )
    )
    op.execute("UPDATE users SET role = 'member' WHERE role = 'user'")
    op.alter_column("users", "updated_at", nullable=False)

    op.create_table(
        "system_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("system_name", sa.String(length=100), nullable=False),
        sa.Column("lab_name", sa.String(length=100), nullable=False),
        sa.Column("llm_api_base", sa.String(length=255), nullable=False),
        sa.Column("llm_api_key", sa.Text(), nullable=False),
        sa.Column("llm_model", sa.String(length=100), nullable=False),
        sa.Column("embedding_api_base", sa.String(length=255), nullable=False),
        sa.Column("embedding_api_key", sa.Text(), nullable=False),
        sa.Column("embedding_model", sa.String(length=100), nullable=False),
        sa.Column("qa_enabled", sa.Boolean(), nullable=False),
        sa.Column("sidebar_auto_collapse", sa.Boolean(), nullable=False),
        sa.Column("theme_mode", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            INSERT INTO system_settings (
                id, system_name, lab_name, llm_api_base, llm_api_key, llm_model,
                embedding_api_base, embedding_api_key, embedding_model,
                qa_enabled, sidebar_auto_collapse, theme_mode, created_at, updated_at
            ) VALUES (
                1, :system_name, :lab_name, '', '', '', '', '', '',
                false, false, 'warm', :created_at, :updated_at
            )
            """
        ),
        {
            "system_name": "实验室知识库",
            "lab_name": "实验室内部",
            "created_at": now,
            "updated_at": now,
        },
    )


def downgrade() -> None:
    op.drop_table("system_settings")
    op.drop_column("users", "last_login_at")
    op.drop_column("users", "updated_at")
    op.drop_column("users", "is_active")
