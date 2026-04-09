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
    can_download: bool = False
    can_rename: bool = False
    can_move: bool = False
    can_copy: bool = False
    can_delete: bool = False

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


class FileRenameRequest(BaseModel):
    file_name: str


class FileMoveRequest(BaseModel):
    folder_id: int | None


class FileCopyRequest(BaseModel):
    folder_id: int | None = None


class BatchDownloadRequest(BaseModel):
    file_ids: list[int]


class ChunkDiagnosticsResponse(BaseModel):
    """单文件 chunk 统计，用于索引质量与调参观测。"""

    file_id: int
    file_name: str
    index_status: str
    pipeline_version: str | None = None
    parent_count: int
    child_count: int
    legacy_count: int
    total_rows: int
    avg_child_token_count: float | None = None
    avg_child_char_count: float | None = None
    p50_child_char: int | None = None
    p90_child_char: int | None = None
    short_child_ratio: float = 0.0
    long_child_ratio: float = 0.0
    block_type_counts: dict[str, int] = {}
    extractor_version: str | None = None
    extractor_rules_version: str | None = None
    parent_block_type_counts: dict[str, int] = {}
    max_heading_depth: int = 0
    special_block_counts: dict[str, int] = {}
