"""add can_download, folder scope/owner, and public/private space roots

Revision ID: g1h2i3j4k5l6
Revises: f7e8d9c0b1a2
Create Date: 2026-04-08

"""

from __future__ import annotations

from datetime import datetime
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "g1h2i3j4k5l6"
down_revision: Union[str, Sequence[str], None] = "f7e8d9c0b1a2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

HOME_NAME = "home"
PUBLIC_NAME = "公共文件夹"
PRIVATE_NAME = "个人文件夹"


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "can_download",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "folders",
        sa.Column(
            "scope",
            sa.String(length=32),
            nullable=False,
            server_default="public",
        ),
    )
    op.add_column("folders", sa.Column("owner_user_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_folders_owner_user_id_users",
        "folders",
        "users",
        ["owner_user_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.execute(
        sa.text(
            "UPDATE users SET role = 'member' "
            "WHERE role IS NULL OR role NOT IN ('root', 'admin', 'member')"
        )
    )
    op.execute(
        sa.text(
            "UPDATE users SET can_download = true WHERE role IN ('root', 'admin')"
        )
    )

    conn = op.get_bind()
    home_row = conn.execute(
        sa.text(
            "SELECT id FROM folders WHERE parent_id IS NULL ORDER BY id ASC LIMIT 1"
        )
    ).fetchone()
    if not home_row:
        op.alter_column("users", "can_download", server_default=None)
        op.alter_column("folders", "scope", server_default=None)
        return

    home_id = home_row[0]
    now = datetime.utcnow()

    def _ensure_child(name: str) -> int:
        row = conn.execute(
            sa.text(
                "SELECT id FROM folders WHERE parent_id = :pid AND name = :n LIMIT 1"
            ),
            {"pid": home_id, "n": name},
        ).fetchone()
        if row:
            return int(row[0])
        rid = conn.execute(
            sa.text(
                "INSERT INTO folders (name, parent_id, created_at, scope, owner_user_id) "
                "VALUES (:name, :pid, :created_at, 'public', NULL) RETURNING id"
            ),
            {"name": name, "pid": home_id, "created_at": now},
        ).scalar_one()
        return int(rid)

    pub_id = _ensure_child(PUBLIC_NAME)
    _ensure_child(PRIVATE_NAME)

    conn.execute(
        sa.text(
            "UPDATE folders SET parent_id = :pub_id "
            "WHERE parent_id = :home_id AND name NOT IN (:n1, :n2)"
        ),
        {"pub_id": pub_id, "home_id": home_id, "n1": PUBLIC_NAME, "n2": PRIVATE_NAME},
    )

    conn.execute(
        sa.text("UPDATE files SET folder_id = :pub_id WHERE folder_id = :home_id"),
        {"pub_id": pub_id, "home_id": home_id},
    )

    conn.execute(
        sa.text("UPDATE folders SET name = :n WHERE id = :id AND name != :n"),
        {"n": HOME_NAME, "id": home_id},
    )

    op.alter_column("users", "can_download", server_default=None)
    op.alter_column("folders", "scope", server_default=None)


def downgrade() -> None:
    op.drop_constraint("fk_folders_owner_user_id_users", "folders", type_="foreignkey")
    op.drop_column("folders", "owner_user_id")
    op.drop_column("folders", "scope")
    op.drop_column("users", "can_download")
