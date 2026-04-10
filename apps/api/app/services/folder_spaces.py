from __future__ import annotations

import re
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.folder import Folder
from app.models.user import User

HOME_NAME = "home"
PUBLIC_ROOT_NAME = "公共文件夹"
PRIVATE_ROOT_NAME = "个人文件夹"
# 顶层「个人文件夹」入口：与公共树根区分，供前端展示私人空间标签（权限仍按目录 id 判定）
PRIVATE_ROOT_SCOPE = "private_root"


def get_home_root(db: Session) -> Folder:
    root = (
        db.query(Folder)
        .filter(Folder.parent_id.is_(None))
        .order_by(Folder.id.asc())
        .first()
    )
    if root is None:
        root = Folder(
            name=HOME_NAME,
            parent_id=None,
            scope="public",
            owner_user_id=None,
            created_at=datetime.utcnow(),
        )
        db.add(root)
        db.commit()
        db.refresh(root)
    if root.name != HOME_NAME:
        root.name = HOME_NAME
        db.commit()
        db.refresh(root)
    return root


def get_public_private_roots(db: Session, home: Folder) -> tuple[Folder | None, Folder | None]:
    pub = (
        db.query(Folder)
        .filter(Folder.parent_id == home.id, Folder.name == PUBLIC_ROOT_NAME)
        .first()
    )
    prv = (
        db.query(Folder)
        .filter(Folder.parent_id == home.id, Folder.name == PRIVATE_ROOT_NAME)
        .first()
    )
    return pub, prv


def ensure_space_roots(db: Session) -> tuple[Folder, Folder, Folder]:
    """
    保证 home 下存在「公共文件夹」「个人文件夹」，并把误挂在 home 下的其它目录并入公共树。
    """
    home = get_home_root(db)
    pub, prv = get_public_private_roots(db, home)
    changed = False
    if pub is None:
        pub = Folder(
            name=PUBLIC_ROOT_NAME,
            parent_id=home.id,
            scope="public",
            owner_user_id=None,
            created_at=datetime.utcnow(),
        )
        db.add(pub)
        changed = True
    if prv is None:
        prv = Folder(
            name=PRIVATE_ROOT_NAME,
            parent_id=home.id,
            scope=PRIVATE_ROOT_SCOPE,
            owner_user_id=None,
            created_at=datetime.utcnow(),
        )
        db.add(prv)
        changed = True
    if changed:
        db.commit()
        db.refresh(pub)
        db.refresh(prv)

    if (
        prv is not None
        and prv.name == PRIVATE_ROOT_NAME
        and (prv.scope or "") == "public"
    ):
        prv.scope = PRIVATE_ROOT_SCOPE
        db.commit()
        db.refresh(prv)

    loose = (
        db.query(Folder)
        .filter(
            Folder.parent_id == home.id,
            ~Folder.name.in_([PUBLIC_ROOT_NAME, PRIVATE_ROOT_NAME]),
        )
        .all()
    )
    if loose:
        for f in loose:
            f.parent_id = pub.id
        db.commit()

    return home, pub, prv


def _safe_slug(username: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9_\-\u4e00-\u9fff]+", "_", (username or "").strip())[:40]
    return s or "user"


def ensure_admin_private_folder(db: Session, admin: User) -> Folder | None:
    r = (admin.role or "").strip().lower()
    if r != "admin":
        return None
    _, _, private_root = ensure_space_roots(db)
    existing = (
        db.query(Folder)
        .filter(
            Folder.parent_id == private_root.id,
            Folder.scope == "admin_private",
            Folder.owner_user_id == admin.id,
        )
        .order_by(Folder.id.asc())
        .first()
    )
    if existing:
        return existing
    name = f"admin_{admin.id}_{_safe_slug(admin.username)}"
    cand = name
    n = 0
    while (
        db.query(Folder)
        .filter(Folder.parent_id == private_root.id, Folder.name == cand)
        .first()
    ):
        n += 1
        cand = f"{name}_{n}"
    folder = Folder(
        name=cand,
        parent_id=private_root.id,
        scope="admin_private",
        owner_user_id=admin.id,
        created_at=datetime.utcnow(),
    )
    db.add(folder)
    db.commit()
    db.refresh(folder)
    return folder


def is_descendant_or_self(db: Session, folder_id: int, ancestor_id: int) -> bool:
    if folder_id == ancestor_id:
        return True
    current = db.query(Folder).filter(Folder.id == folder_id).first()
    if not current:
        return False
    seen: set[int] = set()
    while current is not None and current.id not in seen:
        seen.add(current.id)
        if current.parent_id == ancestor_id:
            return True
        if current.parent_id is None:
            return False
        current = db.query(Folder).filter(Folder.id == current.parent_id).first()
    return False


def get_private_root_id(db: Session) -> int | None:
    home, _, prv = ensure_space_roots(db)
    _ = home
    return prv.id if prv else None


def get_public_root_id(db: Session) -> int | None:
    home, pub, _ = ensure_space_roots(db)
    _ = home
    return pub.id if pub else None
