"""add file index embedding metadata

Revision ID: a1b2c3d4e5f6
Revises: f7e8d9c0b1a2
Create Date: 2026-04-04

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "f7e8d9c0b1a2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("files", sa.Column("index_embedding_provider", sa.String(length=50), nullable=True))
    op.add_column("files", sa.Column("index_embedding_model", sa.String(length=100), nullable=True))
    op.add_column("files", sa.Column("index_embedding_dimension", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("files", "index_embedding_dimension")
    op.drop_column("files", "index_embedding_model")
    op.drop_column("files", "index_embedding_provider")
