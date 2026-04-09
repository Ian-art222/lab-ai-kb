"""merge g1h2i3j4k5l6 (folder scope / can_download) and c2d3e4f5a6b7 (phase2 governance)

Revision ID: m9n8o7p6q5r4
Revises: g1h2i3j4k5l6, c2d3e4f5a6b7
Create Date: 2026-04-08

"""

from typing import Sequence, Union

revision: str = "m9n8o7p6q5r4"
down_revision: Union[str, Sequence[str], None] = ("g1h2i3j4k5l6", "c2d3e4f5a6b7")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
