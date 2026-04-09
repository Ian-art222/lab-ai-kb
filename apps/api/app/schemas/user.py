from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class UserItem(BaseModel):
    id: int
    username: str
    role: str
    is_active: bool
    can_download: bool = False
    created_at: datetime
    updated_at: datetime
    last_login_at: datetime | None = None

    model_config = {"from_attributes": True}


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=6, max_length=128)
    role: Literal["root", "admin", "member"] = "member"
    is_active: bool = True
    can_download: bool = False


class UserUpdate(BaseModel):
    username: str | None = Field(default=None, min_length=3, max_length=50)
    role: Literal["root", "admin", "member"] | None = None
    can_download: bool | None = None

    @model_validator(mode="after")
    def at_least_one_field(self):
        if self.username is None and self.role is None and self.can_download is None:
            raise ValueError("至少提供一个可更新字段")
        return self


class UserStatusUpdate(BaseModel):
    is_active: bool


class UserResetPassword(BaseModel):
    new_password: str = Field(min_length=6, max_length=128)


class UserSelfPasswordUpdate(BaseModel):
    old_password: str
    new_password: str = Field(min_length=6, max_length=128)
