from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.auth import get_current_user, require_user_manager
from app.core.permissions import (
    ROLE_ADMIN,
    ROLE_MEMBER,
    ROLE_ROOT,
    can_assign_role,
    can_delete_user,
    can_disable_user,
    can_list_users,
    can_manage_download_permission,
    can_manage_member,
    effective_role,
    is_last_active_root,
    is_member,
)
from app.core.security import hash_password, verify_password
from app.db.session import get_db
from app.models.user import User
from app.schemas.user import (
    UserCreate,
    UserItem,
    UserResetPassword,
    UserSelfPasswordUpdate,
    UserStatusUpdate,
    UserUpdate,
)
from app.services.folder_spaces import ensure_admin_private_folder

router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("", response_model=list[UserItem])
def list_users(
    q: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_user_manager),
):
    if not can_list_users(current_user):
        raise HTTPException(status_code=403, detail="无权查看用户列表")
    query = db.query(User).order_by(User.created_at.desc())
    if q:
        query = query.filter(User.username.ilike(f"%{q}%"))
    return query.all()


@router.post("", response_model=UserItem)
def create_user(
    data: UserCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_user_manager),
):
    from app.core.permissions import can_create_user_with_role

    nr = (data.role or ROLE_MEMBER).strip().lower()
    if nr not in (ROLE_ROOT, ROLE_ADMIN, ROLE_MEMBER):
        raise HTTPException(status_code=400, detail="无效的角色")
    if not can_create_user_with_role(current_user, nr):
        raise HTTPException(status_code=403, detail="无权创建该角色的用户")

    existing = db.query(User).filter(User.username == data.username).first()
    if existing:
        raise HTTPException(status_code=400, detail="用户名已存在")

    can_dl = bool(data.can_download) if nr == ROLE_MEMBER else True
    user = User(
        username=data.username.strip(),
        password_hash=hash_password(data.password),
        role=nr,
        is_active=data.is_active,
        can_download=can_dl,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    if effective_role(user) == ROLE_ADMIN:
        ensure_admin_private_folder(db, user)
    return user


@router.get("/me", response_model=UserItem)
def get_me(current_user: User = Depends(get_current_user)):
    return current_user


@router.patch("/me/password")
def patch_me_password(
    data: UserSelfPasswordUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not verify_password(data.old_password, current_user.password_hash):
        raise HTTPException(status_code=400, detail="原密码不正确")
    current_user.password_hash = hash_password(data.new_password)
    current_user.updated_at = datetime.utcnow()
    db.commit()
    return {"message": "密码已更新"}


@router.patch("/{user_id}", response_model=UserItem)
def update_user(
    user_id: int,
    data: UserUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_user_manager),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    if not can_manage_member(current_user, user):
        raise HTTPException(status_code=403, detail="无权编辑该用户")

    if data.username is not None:
        uname = data.username.strip()
        if len(uname) < 3:
            raise HTTPException(status_code=400, detail="用户名过短")
        existing = (
            db.query(User)
            .filter(User.username == uname, User.id != user_id)
            .first()
        )
        if existing:
            raise HTTPException(status_code=400, detail="用户名已存在")
        user.username = uname

    if data.role is not None:
        nr = data.role.strip().lower()
        if not can_assign_role(db, current_user, user, nr):
            raise HTTPException(status_code=403, detail="无权修改该用户的角色")
        user.role = nr
        if effective_role(user) in (ROLE_ROOT, ROLE_ADMIN):
            user.can_download = True
        if effective_role(user) == ROLE_ADMIN:
            ensure_admin_private_folder(db, user)

    if data.can_download is not None:
        if not can_manage_download_permission(current_user, user):
            raise HTTPException(status_code=403, detail="无权修改下载权限")
        if not is_member(user):
            raise HTTPException(status_code=400, detail="仅成员账号使用下载开关")
        user.can_download = bool(data.can_download)

    user.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(user)
    return user


@router.patch("/{user_id}/status", response_model=UserItem)
def update_user_status(
    user_id: int,
    data: UserStatusUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_user_manager),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    if not can_manage_member(current_user, user):
        raise HTTPException(status_code=403, detail="无权修改该用户状态")
    if user.id == current_user.id and not data.is_active:
        raise HTTPException(status_code=400, detail="不能禁用当前登录账号")
    if not data.is_active:
        if not can_disable_user(db, current_user, user):
            raise HTTPException(status_code=403, detail="无权禁用该用户")
        if effective_role(user) == ROLE_ROOT and is_last_active_root(db, user):
            raise HTTPException(status_code=400, detail="系统必须保留至少一名启用中的 root")

    user.is_active = data.is_active
    user.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(user)
    return user


@router.delete("/{user_id}")
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_user_manager),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    if not can_delete_user(db, current_user, user):
        raise HTTPException(status_code=403, detail="无权删除该用户")
    db.delete(user)
    db.commit()
    return {"message": "删除成功"}


@router.patch("/{user_id}/reset-password")
def reset_password(
    user_id: int,
    data: UserResetPassword,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_user_manager),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    if not can_manage_member(current_user, user):
        raise HTTPException(status_code=403, detail="无权重置该用户密码")

    user.password_hash = hash_password(data.new_password)
    user.updated_at = datetime.utcnow()
    db.commit()
    return {"message": "密码重置成功"}
