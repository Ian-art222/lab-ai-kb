from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class UserItem(BaseModel):
    id: int
    username: str
    role: str
    is_active: bool
    created_at: datetime
    updated_at: datetime
    last_login_at: datetime | None = None

    model_config = {"from_attributes": True}


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=6, max_length=128)
    role: Literal["admin", "member"] = "member"
    is_active: bool = True


class UserUpdate(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    role: Literal["admin", "member"] = "member"


class UserStatusUpdate(BaseModel):
    is_active: bool


class UserResetPassword(BaseModel):
    new_password: str = Field(min_length=6, max_length=128)
