from pydantic import BaseModel


class IngestFileRequest(BaseModel):
    file_id: int
    force_reindex: bool = False


class AskRequest(BaseModel):
    question: str
    session_id: int | None = None
    scope_type: str = "all"
    folder_id: int | None = None
    file_ids: list[int] | None = None
    strict_mode: bool = True
    top_k: int = 6


class QAMessageItem(BaseModel):
    id: int
    session_id: int
    role: str
    content: str
    references_json: dict | list | None = None
    state: str = "normal"
    created_at: str


class QASessionItem(BaseModel):
    id: int
    title: str
    scope_type: str
    folder_id: int | None = None
    last_question: str | None = None
    last_error: str | None = None
    message_count: int
    updated_at: str
    created_at: str
