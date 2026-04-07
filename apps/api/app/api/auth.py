from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime

from app.core.auth import create_access_token
from app.db.session import get_db
from app.models.user import User
from app.core.security import verify_password
from app.schemas.auth import LoginRequest, LoginResponse

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
def login(data: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == data.username).first()

    if not user:
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    if not verify_password(data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="当前账号已被禁用")

    user.last_login_at = datetime.utcnow()
    db.commit()
    db.refresh(user)
    access_token = create_access_token(user=user)

    return LoginResponse(
        access_token=access_token,
        username=user.username,
        role=user.role,
    )