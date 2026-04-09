from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.file_record import FileRecord
from app.models.folder import Folder
from app.models.user import User
from app.services.folder_spaces import (
    ensure_admin_private_folder,
    ensure_space_roots,
    is_descendant_or_self,
)

ROLE_ROOT = "root"
ROLE_ADMIN = "admin"
ROLE_MEMBER = "member"


def effective_role(user: User) -> str:
    r = (user.role or ROLE_MEMBER).strip().lower()
    if r in (ROLE_ROOT, ROLE_ADMIN, ROLE_MEMBER):
        return r
    return ROLE_MEMBER


def is_root(user: User) -> bool:
    return effective_role(user) == ROLE_ROOT


def is_admin(user: User) -> bool:
    return effective_role(user) == ROLE_ADMIN


def is_member(user: User) -> bool:
    return effective_role(user) == ROLE_MEMBER


def count_active_roots(db: Session) -> int:
    return (
        db.query(User)
        .filter(User.role == ROLE_ROOT, User.is_active.is_(True))
        .count()
    )


def is_last_active_root(db: Session, user: User) -> bool:
    return (
        effective_role(user) == ROLE_ROOT
        and bool(user.is_active)
        and count_active_roots(db) == 1
    )


def can_manage_member(actor: User, target: User) -> bool:
    if is_root(actor):
        return True
    if is_admin(actor) and is_member(target):
        return True
    return False


def can_manage_download_permission(actor: User, target: User) -> bool:
    if not is_member(target):
        return False
    return is_root(actor) or is_admin(actor)


def can_assign_role(db: Session, actor: User, target: User, new_role: str) -> bool:
    if not is_root(actor):
        return False
    nr = (new_role or "").strip().lower()
    if nr not in (ROLE_ROOT, ROLE_ADMIN, ROLE_MEMBER):
        return False
    if (
        effective_role(target) == ROLE_ROOT
        and target.is_active
        and nr != ROLE_ROOT
        and is_last_active_root(db, target)
    ):
        return False
    return True


def can_disable_user(db: Session, actor: User, target: User) -> bool:
    if is_member(actor):
        return False
    if is_admin(actor):
        return is_member(target)
    if is_root(actor):
        if (
            effective_role(target) == ROLE_ROOT
            and target.is_active
            and is_last_active_root(db, target)
        ):
            return False
        return True
    return False


def can_delete_user(db: Session, actor: User, target: User) -> bool:
    if not is_root(actor):
        return False
    if effective_role(target) == ROLE_ROOT and is_last_active_root(db, target):
        return False
    return True


def _own_private_root(db: Session, user: User) -> Folder | None:
    if not is_admin(user):
        return None
    return ensure_admin_private_folder(db, user)


def can_view_folder(db: Session, user: User, folder: Folder | None) -> bool:
    if folder is None:
        return False
    home, pub, prv = ensure_space_roots(db)
    if folder.id == home.id:
        return True
    if is_root(user):
        return True

    pub_id = pub.id
    prv_id = prv.id

    if is_member(user):
        if folder.id == prv_id:
            return False
        if is_descendant_or_self(db, folder.id, prv_id):
            return False
        return folder.id == pub_id or is_descendant_or_self(db, folder.id, pub_id)

    if is_admin(user):
        own = _own_private_root(db, user)
        own_id = own.id if own else None
        if folder.id == prv_id:
            return True
        if own_id and (
            folder.id == own_id or is_descendant_or_self(db, folder.id, own_id)
        ):
            return True
        return folder.id == pub_id or is_descendant_or_self(db, folder.id, pub_id)

    return False


def can_manage_folder_structure(db: Session, user: User, folder: Folder | None) -> bool:
    if folder is None:
        return False
    home, pub, prv = ensure_space_roots(db)
    if folder.parent_id is None:
        return False
    if is_member(user):
        return False
    if is_root(user):
        if folder.id in (home.id, pub.id, prv.id):
            return folder.id != home.id
        return True
    if is_admin(user):
        if folder.id in (home.id, pub.id, prv.id):
            return False
        own = _own_private_root(db, user)
        if not own:
            return False
        return folder.id == own.id or is_descendant_or_self(db, folder.id, own.id)
    return False


def can_create_top_level_space_folder(db: Session, user: User, parent: Folder) -> bool:
    home, _, _ = ensure_space_roots(db)
    if parent.id != home.id:
        return True
    return is_root(user)


def can_upload_file_to_folder(db: Session, user: User, folder: Folder | None) -> bool:
    if folder is None:
        return False
    if not can_view_folder(db, user, folder):
        return False
    home, pub, prv = ensure_space_roots(db)
    if is_member(user):
        return folder.id == pub.id or is_descendant_or_self(db, folder.id, pub.id)
    if is_admin(user):
        if folder.id == prv.id:
            return False
        return True
    if is_root(user):
        return True
    return False


def user_effective_can_download(user: User) -> bool:
    if is_root(user) or is_admin(user):
        return True
    return bool(user.can_download)


def can_download_file_in_folder(db: Session, user: User, folder_id: int | None) -> bool:
    if folder_id is None:
        return False
    folder = db.query(Folder).filter(Folder.id == folder_id).first()
    if not folder or not can_view_folder(db, user, folder):
        return False
    return user_effective_can_download(user)


def can_download_file(db: Session, user: User, file_record: FileRecord) -> bool:
    return can_download_file_in_folder(db, user, file_record.folder_id)


def can_move_file(
    db: Session, user: User, file_record: FileRecord, dest_folder: Folder
) -> bool:
    if is_member(user):
        return False
    src_folder = db.query(Folder).filter(Folder.id == file_record.folder_id).first()
    if not src_folder or not can_view_folder(db, user, src_folder):
        return False
    if not can_upload_file_to_folder(db, user, dest_folder):
        return False
    return is_root(user) or is_admin(user)


def can_create_folder_in_parent(db: Session, user: User, parent: Folder) -> bool:
    home, _, _ = ensure_space_roots(db)
    if parent.id == home.id:
        return False
    if is_member(user):
        return False
    if is_root(user):
        return True
    if is_admin(user):
        own = _own_private_root(db, user)
        if not own:
            return False
        return parent.id == own.id or is_descendant_or_self(db, parent.id, own.id)
    return False


def can_reparent_folder(db: Session, user: User, folder: Folder, new_parent: Folder) -> bool:
    if not can_manage_folder_structure(db, user, folder):
        return False
    return can_create_folder_in_parent(db, user, new_parent)


def can_copy_file(
    db: Session, user: User, file_record: FileRecord, dest_folder: Folder
) -> bool:
    return can_move_file(db, user, file_record, dest_folder)


def can_delete_file(db: Session, user: User, file_record: FileRecord) -> bool:
    if is_member(user):
        return False
    folder = db.query(Folder).filter(Folder.id == file_record.folder_id).first()
    if not folder:
        return False
    if not can_view_folder(db, user, folder):
        return False
    return is_root(user) or is_admin(user)


def can_rename_file(db: Session, user: User, file_record: FileRecord) -> bool:
    """与删除一致：member 不可；admin/root 在可浏览目录内可改文件名。"""
    return can_delete_file(db, user, file_record)


def can_access_ops_pages(user: User) -> bool:
    return is_root(user)


def can_access_system_settings(user: User) -> bool:
    return is_root(user)


def can_list_users(user: User) -> bool:
    return is_root(user) or is_admin(user)


def can_create_user_with_role(actor: User, new_role: str) -> bool:
    nr = (new_role or "").strip().lower()
    if is_member(actor):
        return False
    if is_admin(actor):
        return nr == ROLE_MEMBER
    if is_root(actor):
        return nr in (ROLE_ROOT, ROLE_ADMIN, ROLE_MEMBER)
    return False


def user_may_access_file_record(db: Session, user: User, file_record: FileRecord) -> bool:
    folder = db.query(Folder).filter(Folder.id == file_record.folder_id).first()
    if not folder:
        return False
    return can_view_folder(db, user, folder)
