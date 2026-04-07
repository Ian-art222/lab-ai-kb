from typing import Any

from pydantic import BaseModel, Field


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
    candidate_k: int | None = None
    max_context_chars: int | None = None
    neighbor_window: int | None = None
    dedupe_adjacent_chunks: bool | None = None
    rerank_enabled: bool | None = None
    rerank_top_n: int | None = None


class RetrievalMetaPayload(BaseModel):
    """Normalized retrieval metadata returned on successful /api/qa/ask responses."""

    retrieval_strategy: str = Field(
        description="Fixed strategy label, e.g. app_layer_cosine_topk"
    )
    answer_source: str = Field(
        description="knowledge_base | knowledge_base_low_confidence | model_general (error only on client for failures)"
    )

    scope_type: str
    strict_mode: bool
    top_k: int
    min_similarity_score: float
    candidate_chunks: int
    matched_chunks: int
    selected_chunks: int
    compatible_file_count: int
    used_file_ids: list[int]
    min_score: float | None = Field(
        default=None,
        description="Legacy alias of min_similarity_score; kept for backward compatibility",
    )
    candidate_k: int | None = None
    expanded_chunks: int | None = None
    packed_chunks: int | None = None
    context_chars: int | None = None
    neighbor_window: int | None = None
    dedupe_adjacent_chunks: bool | None = None
    retrieval_mode: str | None = None
    semantic_candidate_count: int | None = None
    lexical_candidate_count: int | None = None
    fusion_method: str | None = None
    rerank_enabled: bool | None = None
    rerank_input_count: int | None = None
    rerank_output_count: int | None = None
    rerank_model_name: str | None = None
    rerank_applied: bool | None = None
    parent_recovered_chunks: int | None = None
    parent_deduped_groups: int | None = None


class AskSuccessResponse(BaseModel):
    """Shape of a successful POST /api/qa/ask JSON body (session fields merged in the router)."""

    session_id: int
    assistant_message_id: int
    answer: str
    references: list[Any]
    references_json: Any
    answer_source: str
    used_files: list[int]
    retrieval_meta: RetrievalMetaPayload


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

