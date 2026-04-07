"""add folders table and file folder_id

Revision ID: e3a1b2c3d4e5
Revises: 22bbab6c5ece
Create Date: 2026-04-03 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e3a1b2c3d4e5"
down_revision: Union[str, Sequence[str], None] = "22bbab6c5ece"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # create folders table
    op.create_table(
        "folders",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_folders_id"), "folders", ["id"], unique=False)
    op.create_index(op.f("ix_folders_name"), "folders", ["name"], unique=True)

    # add folder_id to files
    op.add_column("files", sa.Column("folder_id", sa.Integer(), nullable=True))
    op.create_index(
        op.f("ix_files_folder_id"), "files", ["folder_id"], unique=False
    )

    fk_name = op.f("fk_files_folder_id_folders")
    op.create_foreign_key(
        fk_name,
        "files",
        "folders",
        ["folder_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    # drop foreign key first
    fk_name = op.f("fk_files_folder_id_folders")
    op.drop_constraint(fk_name, "files", type_="foreignkey")

    op.drop_index(op.f("ix_files_folder_id"), table_name="files")
    op.drop_column("files", "folder_id")

    op.drop_index(op.f("ix_folders_name"), table_name="folders")
    op.drop_index(op.f("ix_folders_id"), table_name="folders")
    op.drop_table("folders")

