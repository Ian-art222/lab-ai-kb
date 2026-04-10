"""files: index_status_updated_at + index_run_started_at for stale reclaim

Revision ID: t2u3v4w5x6y7
Revises: n1o2p3q4r5s6
Create Date: 2026-04-09

- index_status_updated_at: 每次 index_status 变化或显式心跳时更新，供 processing 类僵尸判定
- index_run_started_at: 本轮后台任务实际进入 indexing 时写入；排队 pending 时清空，供「从未开始」判定

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "t2u3v4w5x6y7"
down_revision: Union[str, Sequence[str], None] = "n1o2p3q4r5s6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("files", sa.Column("index_status_updated_at", sa.DateTime(), nullable=True))
    op.add_column("files", sa.Column("index_run_started_at", sa.DateTime(), nullable=True))
    op.execute(
        sa.text(
            "UPDATE files SET index_status_updated_at = COALESCE(indexed_at, upload_time) "
            "WHERE index_status_updated_at IS NULL"
        )
    )


def downgrade() -> None:
    op.drop_column("files", "index_run_started_at")
    op.drop_column("files", "index_status_updated_at")
