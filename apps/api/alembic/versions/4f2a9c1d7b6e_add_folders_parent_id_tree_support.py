"""add folders parent_id for tree hierarchy

This migration converts `folders.name` global uniqueness into
`unique(parent_id, name)` and adds `folders.parent_id` (self FK).
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "4f2a9c1d7b6e"
down_revision: Union[str, Sequence[str], None] = "e3a1b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1) add parent_id column (nullable for existing rows)
    op.add_column("folders", sa.Column("parent_id", sa.Integer(), nullable=True))
    op.create_index(op.f("ix_folders_parent_id"), "folders", ["parent_id"], unique=False)

    # 2) add self-referencing FK (deleting a parent keeps children as root)
    op.create_foreign_key(
        "fk_folders_parent_id_folders",
        "folders",
        "folders",
        ["parent_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # 3) replace global unique(name) with unique(parent_id, name)
    # Existing `folders.name` unique index is created in `e3a1b2c3d4e5`.
    op.drop_index(op.f("ix_folders_name"), table_name="folders")
    op.create_unique_constraint(
        "uq_folders_parent_id_name", "folders", ["parent_id", "name"]
    )


def downgrade() -> None:
    # reverse: unique(parent_id, name) -> unique(name)
    op.drop_constraint(
        "uq_folders_parent_id_name", "folders", type_="unique"
    )

    # restore previous unique index on folders.name
    op.create_index(
        op.f("ix_folders_name"), "folders", ["name"], unique=True
    )

    # drop FK + index + column
    op.drop_constraint(
        "fk_folders_parent_id_folders", "folders", type_="foreignkey"
    )
    op.drop_index(op.f("ix_folders_parent_id"), table_name="folders")
    op.drop_column("folders", "parent_id")

