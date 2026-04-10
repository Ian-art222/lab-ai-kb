import { apiFetch, parseHttpErrorPayload } from './client'

export type ScopeType = 'all' | 'folder' | 'files'

export interface AskReference {
  file_id: number
  file_name: string
  chunk_id: number
  chunk_index: number
  snippet: string
  score: number
  section_title?: string | null
  page_number?: number | null
  heading_path?: string | null
  block_type?: string | null
  chunk_role?: string | null
  /** 引用对应的检索命中 child（非扩展段落） */
  ref_origin?: string | null
  /** 实际写入上下文的角色：parent_primary / parent_with_adjacent_expansion / child_primary */
  context_chunk_role?: string | null
  provenance_type?: string | null
  provenance_tags?: string[] | null
  source_reason?: string | null
  matched_query_index?: number | null
  matched_query?: string | null
  query_type?: string | null
  rerank_score?: number | null
  source_file_rank?: number | null
  file_char_share?: number | null
  parent_chunk_id?: number | null
  parent_sequence_index?: number | null
  adjacent_expansion?: boolean | null
  adjacent_parent_chunk_ids?: number[] | null
}

export type AnswerSource =
  | 'knowledge_base'
  | 'knowledge_base_low_confidence'
  | 'model_general'
  | 'error'

/** 与后端 retrieval_meta.answer_synthesis 对齐（仅列常用键，其余可走 Record） */
export interface AnswerSynthesisTrace {
  query_type?: string | null
  coverage_assessment?: string | null
  coverage_shortfall?: boolean | null
  requires_multi_source_but_missing?: boolean | null
  dominant_source_warning?: boolean | null
  citation_source_count?: number | null
  coverage_shortfall_prompt_applied?: boolean | null
  [key: string]: unknown
}

/** 与后端 retrieval_meta.coverage_diagnostics 对齐（宽松） */
export interface CoverageDiagnostics {
  query_type?: string | null
  distinct_files_pre_pack?: number | null
  distinct_files_post_pack?: number | null
  dominant_file_ratio_post_pack?: number | null
  dominant_file_ratio_chunks?: number | null
  selected_file_distribution?: Record<string, number> | null
  unmatched_queries?: string[] | null
  weak_query_indices?: string[] | null
  coverage_by_query?: Record<string, unknown> | null
  coverage_shortfall?: Record<string, unknown> | null
  dominant_source_warning?: boolean | null
  citation_source_count?: number | null
  packing_decision_trace?: Record<string, unknown> | null
  [key: string]: unknown
}

export interface RetrievalMeta {
  retrieval_strategy: string
  answer_source: AnswerSource
  scope_type: ScopeType
  strict_mode: boolean
  top_k: number
  min_similarity_score: number
  candidate_chunks: number
  matched_chunks: number
  selected_chunks: number
  compatible_file_count: number
  used_file_ids: number[]
  /** @deprecated same as min_similarity_score; kept for older responses */
  min_score?: number | null
  candidate_k?: number | null
  expanded_chunks?: number | null
  packed_chunks?: number | null
  context_chars?: number | null
  neighbor_window?: number | null
  dedupe_adjacent_chunks?: boolean | null
  retrieval_mode?: string | null
  semantic_candidate_count?: number | null
  lexical_candidate_count?: number | null
  fusion_method?: string | null
  rerank_enabled?: boolean | null
  rerank_input_count?: number | null
  rerank_output_count?: number | null
  rerank_model_name?: string | null
  rerank_applied?: boolean | null
  parent_recovered_chunks?: number | null
  parent_deduped_groups?: number | null
  task_type?: string | null
  selected_scope?: string | null
  selected_skill?: string | null
  workflow_summary?: string | null
  fallback_triggered?: boolean | null
  stop_reason?: string | null
  source_count?: number | null
  dominant_source_ratio?: number | null
  multi_source_coverage?: number | null
  clarification_needed?: boolean | null
  compare_result?: Record<string, unknown> | null
  /** 开启 qa_debug_retrieval_trace_enabled 时由后端填充 */
  retrieval_trace?: Record<string, unknown> | null
  query_understanding?: Record<string, unknown> | null
  answer_synthesis?: AnswerSynthesisTrace | Record<string, unknown> | null
  coverage_diagnostics?: CoverageDiagnostics | null
}

export interface AskResponse {
  session_id: number
  assistant_message_id: number
  answer: string
  references: AskReference[]
  used_files: number[]
  retrieval_meta: RetrievalMeta
  answer_source: AnswerSource
  task_type?: string | null
  selected_skill?: string | null
  workflow_summary?: string | null
  clarification_needed?: boolean | null
  compare_result?: Record<string, unknown> | null
  planner_meta?: Record<string, unknown> | null
}

export interface CreateSessionResponse {
  session_id: number
}

export interface IngestFileRequest {
  file_id: number
  force_reindex?: boolean
}

export interface IndexStatusResponse {
  file_id: number
  index_status: string
  indexed_at?: string | null
  index_error?: string | null
  index_warning?: string | null
  queued?: boolean
  /** 未入队原因，例如 ingest_already_running_in_worker */
  skip_reason?: string | null
}

export interface QAMessageItem {
  id: number
  session_id: number
  role: 'user' | 'assistant'
  content: string
  references_json?: AskReference[] | Record<string, unknown> | null
  state?: 'normal' | 'error'
  created_at: string
}

export interface QASessionMessagesResponse {
  session_id: number
  messages: QAMessageItem[]
}

export interface QASessionItem {
  id: number
  title: string
  scope_type: ScopeType
  folder_id?: number | null
  last_question?: string | null
  last_error?: string | null
  message_count: number
  updated_at: string
  created_at: string
}

export interface QASessionListResponse {
  sessions: QASessionItem[]
}

export class QaApiError extends Error {
  code?: string

  constructor(message: string, code?: string) {
    super(message)
    this.name = 'QaApiError'
    this.code = code
  }
}

async function parseQaJson<T>(response: Response, errorFallback: string): Promise<T> {
  const text = await response.text()
  if (!response.ok) {
    const p = parseHttpErrorPayload(text, response.status, errorFallback)
    throw new QaApiError(p.message, p.code)
  }
  if (!text.trim()) {
    throw new QaApiError(`${errorFallback}：空响应`)
  }
  try {
    return JSON.parse(text) as T
  } catch {
    throw new QaApiError(`${errorFallback}：响应不是合法 JSON`)
  }
}

export async function createSessionApi(): Promise<CreateSessionResponse> {
  const response = await apiFetch('/qa/sessions', { method: 'POST' })
  return parseQaJson<CreateSessionResponse>(response, '创建会话失败')
}

export async function getSessionsApi(): Promise<QASessionListResponse> {
  const response = await apiFetch('/qa/sessions')
  return parseQaJson<QASessionListResponse>(response, '获取会话列表失败')
}

export async function askApi(params: {
  question: string
  session_id?: number | null
  scope_type: ScopeType
  folder_id?: number | null
  file_ids?: number[]
  strict_mode?: boolean
  top_k?: number
  candidate_k?: number | null
  max_context_chars?: number | null
  neighbor_window?: number | null
  dedupe_adjacent_chunks?: boolean | null
  rerank_enabled?: boolean | null
  rerank_top_n?: number | null
}): Promise<AskResponse> {
  const body: any = {
    question: params.question,
    session_id: params.session_id ?? null,
    scope_type: params.scope_type,
    folder_id: params.folder_id ?? null,
    file_ids: params.file_ids ?? null,
    strict_mode: params.strict_mode ?? true,
    top_k: params.top_k ?? 6,
    candidate_k: params.candidate_k ?? null,
    max_context_chars: params.max_context_chars ?? null,
    neighbor_window: params.neighbor_window ?? null,
    dedupe_adjacent_chunks: params.dedupe_adjacent_chunks ?? null,
    rerank_enabled: params.rerank_enabled ?? null,
    rerank_top_n: params.rerank_top_n ?? null,
  }

  const response = await apiFetch('/qa/ask', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })

  return parseQaJson<AskResponse>(response, '提问失败')
}

export async function ingestFileApi(data: IngestFileRequest): Promise<IndexStatusResponse> {
  const response = await apiFetch('/qa/ingest/file', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  return parseQaJson<IndexStatusResponse>(response, '索引失败')
}

export async function getFileIndexStatusApi(fileId: number): Promise<IndexStatusResponse> {
  const response = await apiFetch(`/qa/files/${fileId}/index-status`)
  return parseQaJson<IndexStatusResponse>(response, '获取索引状态失败')
}

export async function getSessionMessagesApi(sessionId: number): Promise<QASessionMessagesResponse> {
  const response = await apiFetch(`/qa/sessions/${sessionId}/messages`)
  return parseQaJson<QASessionMessagesResponse>(response, '获取会话消息失败')
}

export async function deleteSessionApi(sessionId: number): Promise<{ message: string }> {
  const response = await apiFetch(`/qa/sessions/${sessionId}`, { method: 'DELETE' })
  return parseQaJson<{ message: string }>(response, '删除会话失败')
}
