from __future__ import annotations

from types import SimpleNamespace

from app.core.permissions import (
    ROLE_MEMBER,
    can_manage_member,
    effective_role,
    is_root,
)


def test_effective_role_normalizes() -> None:
    assert effective_role(SimpleNamespace(role=" Admin ")) == "admin"
    assert effective_role(SimpleNamespace(role="ROOT")) == "root"
    assert effective_role(SimpleNamespace(role="bogus")) == ROLE_MEMBER


def test_can_manage_member_matrix() -> None:
    root = SimpleNamespace(role="root")
    admin = SimpleNamespace(role="admin")
    mem = SimpleNamespace(role="member")
    assert can_manage_member(root, admin)
    assert can_manage_member(root, mem)
    assert can_manage_member(admin, mem)
    assert not can_manage_member(admin, root)
    assert not can_manage_member(admin, admin)
    assert not can_manage_member(mem, mem)


def test_is_root() -> None:
    assert is_root(SimpleNamespace(role="root"))
    assert not is_root(SimpleNamespace(role="admin"))
