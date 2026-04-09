from typing import Any

from pydantic import BaseModel, ConfigDict, Field


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

    model_config = ConfigDict(extra="allow")

    retrieval_strategy: str = Field(
        description="Runtime strategy label, e.g. pgvector_ann_hnsw | app_layer_cosine_topk | fts_websearch_rrf"
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
    normalized_query: str | None = None
    rewritten_queries: list[str] | None = None
    abstain_reason: str | None = None
    abstain_reason_code: str | None = None
    failure_reason_code: str | None = None
    trace_id: str | None = None
    request_id: str | None = None
    task_type: str | None = None
    planner_output: dict[str, Any] | None = None
    selected_strategy: str | None = None
    workflow_steps_json: list[dict[str, Any]] | None = None
    tool_traces_json: list[dict[str, Any]] | None = None
    session_context_json: dict[str, Any] | None = None
    final_answer_type: str | None = None
    selected_scope: str | None = None
    selected_skill: str | None = None
    planner_meta: dict[str, Any] | None = None
    compare_result: dict[str, Any] | None = None
    clarification_needed: bool | None = None
    workflow_summary: str | None = None
    source_count: int | None = None
    dominant_source_ratio: float | None = None
    multi_source_coverage: float | None = None
    fallback_triggered: bool | None = None
    retrieval_rounds: int | None = None
    stop_reason: str | None = None
    retrieval_trace: dict[str, Any] | None = None
    query_understanding: dict[str, Any] | None = None
    answer_synthesis: dict[str, Any] | None = None
    coverage_diagnostics: dict[str, Any] | None = Field(
        default=None,
        description="Pre/post pack coverage stats, per-query hit counts, packing trace, coverage_shortfall",
    )


class QACitationReferencePayload(BaseModel):
    """Optional structured citation; API may return extra keys (extra=allow)."""

    model_config = ConfigDict(extra="allow")

    file_id: int | None = None
    file_name: str | None = None
    chunk_id: int | None = None
    chunk_index: int | None = None
    snippet: str | None = None
    score: float | None = None
    heading_path: str | None = None
    block_type: str | None = None
    chunk_role: str | None = None
    context_chunk_role: str | None = None
    provenance_type: str | None = None
    provenance_tags: list[str] | None = None
    source_reason: str | None = None
    matched_query_index: int | None = None
    matched_query: str | None = None
    query_type: str | None = None
    rerank_score: float | None = None
    source_file_rank: int | None = None
    file_char_share: float | None = None
    parent_chunk_id: int | None = None
    parent_sequence_index: int | None = None


class AnswerSynthesisTracePayload(BaseModel):
    """Subset of keys written to retrieval_meta.answer_synthesis for typing / OpenAPI."""

    model_config = ConfigDict(extra="allow")

    query_type: str | None = None
    coverage_assessment: str | None = None
    coverage_shortfall: bool | None = None
    requires_multi_source_but_missing: bool | None = None
    dominant_source_warning: bool | None = None
    citation_source_count: int | None = None
    coverage_shortfall_prompt_applied: bool | None = None


class AskSuccessResponse(BaseModel):
    """Shape of a successful POST /api/qa/ask JSON body (session fields merged in the router)."""

    session_id: int
    assistant_message_id: int
    answer: str
    references: list[Any]
    references_json: Any
    evidence_bundles: Any | None = None
    answer_source: str
    used_files: list[int]
    retrieval_meta: RetrievalMetaPayload
    task_type: str | None = None
    selected_skill: str | None = None
    planner_meta: dict[str, Any] | None = None
    compare_result: dict[str, Any] | None = None
    clarification_needed: bool | None = None
    workflow_summary: str | None = None


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
