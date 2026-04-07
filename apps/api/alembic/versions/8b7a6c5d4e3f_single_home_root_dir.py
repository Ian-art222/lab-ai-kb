"""ensure a single fixed root folder named 'home'

Rules enforced by this migration:
- There must be exactly one folder with `parent_id IS NULL`.
- That folder's name is forced to 'home'.
- Any additional illegal root folders are moved under the home root.
  If name conflicts happen under home, they are renamed deterministically.
- Any FileRecord with folder_id IS NULL is moved under the home root folder.
- Add a partial unique index to prevent future insertion of a second root.
"""

from datetime import datetime
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "8b7a6c5d4e3f"
down_revision: Union[str, Sequence[str], None] = "4f2a9c1d7b6e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


HOME_NAME = "home"
SINGLE_ROOT_INDEX = "uq_folders_single_root"


def upgrade() -> None:
    conn = op.get_bind()
    if hasattr(conn, "connect"):
        conn = conn.connect()

    roots = conn.execute(
        sa.text(
            "SELECT id, name FROM folders WHERE parent_id IS NULL ORDER BY id ASC"
        )
    ).fetchall()

    now = datetime.utcnow()

    if not roots:
        home_id = conn.execute(
            sa.text(
                "INSERT INTO folders (name, parent_id, created_at) "
                "VALUES (:name, NULL, :created_at) RETURNING id"
            ),
            {"name": HOME_NAME, "created_at": now},
        ).scalar_one()
    else:
        home_id = roots[0][0]

        # Force the primary root name
        conn.execute(
            sa.text("UPDATE folders SET name = :name WHERE id = :id"),
            {"name": HOME_NAME, "id": home_id},
        )

        # Move other illegal roots under home
        for root_id, root_name in roots[1:]:
            candidate = root_name
            if not candidate:
                candidate = f"folder_{root_id}"

            # Ensure uniqueness under home (parent_id = home_id)
            idx = 0
            while (
                conn.execute(
                    sa.text(
                        "SELECT 1 FROM folders WHERE parent_id = :pid AND name = :n LIMIT 1"
                    ),
                    {"pid": home_id, "n": candidate},
                ).fetchone()
                is not None
            ):
                idx += 1
                candidate = f"{root_name}_{root_id}_{idx}"

            conn.execute(
                sa.text(
                    "UPDATE folders SET parent_id = :pid, name = :n WHERE id = :id"
                ),
                {"pid": home_id, "n": candidate, "id": root_id},
            )

    # Migrate root-level files (folder_id IS NULL) under home root
    conn.execute(
        sa.text("UPDATE files SET folder_id = :home_id WHERE folder_id IS NULL"),
        {"home_id": home_id},
    )

    # Enforce single-root invariant at DB level
    op.execute(f"DROP INDEX IF EXISTS {SINGLE_ROOT_INDEX}")
    op.execute(
        f"CREATE UNIQUE INDEX {SINGLE_ROOT_INDEX} ON folders ((1)) WHERE parent_id IS NULL"
    )


def downgrade() -> None:
    # Keep data as-is; only relax the invariant.
    op.execute(f"DROP INDEX IF EXISTS {SINGLE_ROOT_INDEX}")

