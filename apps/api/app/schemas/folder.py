from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.file import FileItem


class FolderItem(BaseModel):
    id: int
    name: str
    parent_id: int | None
    scope: str = "public"
    owner_user_id: int | None = None
    created_at: datetime
    can_manage_structure: bool | None = None
    can_open: bool = True
    can_rename_folder: bool = False
    can_delete_folder: bool = False
    can_move_folder: bool = False

    model_config = {"from_attributes": True}


class FolderCreate(BaseModel):
    name: str
    parent_id: int | None = None


class FolderTreeItem(BaseModel):
    id: int
    name: str
    parent_id: int | None
    scope: str = "public"
    owner_user_id: int | None = None
    can_manage_structure: bool | None = None
    children: list[FolderTreeItem] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class BreadcrumbItem(BaseModel):
    id: int
    name: str


class FolderViewUi(BaseModel):
    can_manage_structure: bool
    can_create_subfolder: bool
    can_upload: bool
    can_download_files: bool
    can_move_or_delete_files: bool


class FolderChildrenResponse(BaseModel):
    current_folder: FolderItem | None
    breadcrumbs: list[BreadcrumbItem]
    folders: list[FolderItem]
    files: list[FileItem]
    ui: FolderViewUi
    space_label: str = ""
    space_kind: str = ""


class FolderRenameRequest(BaseModel):
    name: str


class FolderMoveRequest(BaseModel):
    parent_id: int | None


FolderTreeItem.model_rebuild()

