from __future__ import annotations

import os
import sys
from datetime import UTC, datetime

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from app.core.security import hash_password
from app.db.session import SessionLocal
from app.models.user import User


def main() -> int:
    if len(sys.argv) != 3:
        print("Usage: python scripts/create_admin.py <username> <password>")
        return 1

    username = sys.argv[1].strip()
    password = sys.argv[2]
    if len(username) < 3 or len(password) < 6:
        print("Username must be at least 3 chars and password at least 6 chars.")
        return 1

    db = SessionLocal()
    try:
        existing = db.query(User).filter(User.username == username).first()
        now = datetime.now(UTC).replace(tzinfo=None)
        if existing:
            existing.password_hash = hash_password(password)
            existing.role = "admin"
            existing.is_active = True
            existing.updated_at = now
            db.commit()
            print(f"Updated existing user '{username}' as admin.")
            return 0

        user = User(
            username=username,
            password_hash=hash_password(password),
            role="admin",
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        db.add(user)
        db.commit()
        print(f"Created admin user '{username}'.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())