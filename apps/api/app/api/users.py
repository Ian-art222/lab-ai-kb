from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.auth import get_current_user, require_admin
from app.core.security import hash_password
from app.db.session import get_db
from app.models.user import User
from app.schemas.user import (
    UserCreate,
    UserItem,
    UserResetPassword,
    UserStatusUpdate,
    UserUpdate,
)

router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("", response_model=list[UserItem])
def list_users(
    q: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    query = db.query(User).order_by(User.created_at.desc())
    if q:
        query = query.filter(User.username.ilike(f"%{q}%"))
    return query.all()


@router.post("", response_model=UserItem)
def create_user(
    data: UserCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    existing = db.query(User).filter(User.username == data.username).first()
    if existing:
        raise HTTPException(status_code=400, detail="用户名已存在")

    user = User(
        username=data.username.strip(),
        password_hash=hash_password(data.password),
        role=data.role,
        is_active=data.is_active,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.patch("/{user_id}", response_model=UserItem)
def update_user(
    user_id: int,
    data: UserUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    existing = (
        db.query(User)
        .filter(User.username == data.username, User.id != user_id)
        .first()
    )
    if existing:
        raise HTTPException(status_code=400, detail="用户名已存在")

    user.username = data.username.strip()
    user.role = data.role
    user.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(user)
    return user


@router.patch("/{user_id}/status", response_model=UserItem)
def update_user_status(
    user_id: int,
    data: UserStatusUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    if user.id == current_user.id and not data.is_active:
        raise HTTPException(status_code=400, detail="不能禁用当前登录管理员")

    user.is_active = data.is_active
    user.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(user)
    return user


@router.patch("/{user_id}/reset-password")
def reset_password(
    user_id: int,
    data: UserResetPassword,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    user.password_hash = hash_password(data.new_password)
    user.updated_at = datetime.utcnow()
    db.commit()
    return {"message": "密码重置成功"}


@router.get("/me")
def get_me(current_user: User = Depends(get_current_user)):
    return {
        "id": current_user.id,
        "username": current_user.username,
        "role": current_user.role,
        "is_active": current_user.is_active,
    }
