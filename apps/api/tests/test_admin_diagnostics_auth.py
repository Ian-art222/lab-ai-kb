import unittest

from fastapi import HTTPException

from app.api.admin_diagnostics import _require_admin


class _User:
    def __init__(self, role: str):
        self.role = role


class TestAdminDiagnosticsAuth(unittest.TestCase):
    def test_admin_allowed(self):
        user = _User("admin")
        out = _require_admin(user)  # type: ignore[arg-type]
        self.assertEqual(out.role, "admin")

    def test_member_forbidden(self):
        user = _User("member")
        with self.assertRaises(HTTPException) as exc:
            _require_admin(user)  # type: ignore[arg-type]
        self.assertEqual(exc.exception.status_code, 403)


if __name__ == "__main__":
    unittest.main()

