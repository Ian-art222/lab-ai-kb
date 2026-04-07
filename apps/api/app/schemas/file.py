from datetime import datetime

from pydantic import BaseModel


class FileItem(BaseModel):
    id: int
    file_name: str
    file_type: str
    uploader: str
    upload_time: datetime
    folder_id: int | None = None
    folder_name: str | None = None
    index_status: str
    indexed_at: datetime | None = None
    index_error: str | None = None
    index_warning: str | None = None
    mime_type: str | None = None
    file_size: int | None = None

    model_config = {"from_attributes": True}


class FileMetaItem(BaseModel):
    id: int
    file_name: str
    file_type: str
    uploader: str
    upload_time: datetime
    folder_id: int | None = None
    folder_name: str | None = None
    size: int | None = None
    index_status: str
    indexed_at: datetime | None = None
    index_error: str | None = None
    index_warning: str | None = None
    mime_type: str | None = None
    content_hash: str | None = None
    file_size: int | None = None

    model_config = {"from_attributes": True}


class FileMoveRequest(BaseModel):
    folder_id: int | None


class BatchDownloadRequest(BaseModel):
    file_ids: list[int]
