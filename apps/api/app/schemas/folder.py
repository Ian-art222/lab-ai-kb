from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.file import FileItem


class FolderItem(BaseModel):
    id: int
    name: str
    parent_id: int | None
    created_at: datetime

    model_config = {"from_attributes": True}


class FolderCreate(BaseModel):
    name: str
    parent_id: int | None = None


class FolderTreeItem(BaseModel):
    id: int
    name: str
    parent_id: int | None
    children: list[FolderTreeItem] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class BreadcrumbItem(BaseModel):
    id: int
    name: str


class FolderChildrenResponse(BaseModel):
    current_folder: FolderItem | None
    breadcrumbs: list[BreadcrumbItem]
    folders: list[FolderItem]
    files: list[FileItem]


class FolderRenameRequest(BaseModel):
    name: str


class FolderMoveRequest(BaseModel):
    parent_id: int | None


FolderTreeItem.model_rebuild()

