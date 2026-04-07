import { apiFetch } from './client'

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
}

export type AnswerSource =
  | 'knowledge_base'
  | 'knowledge_base_low_confidence'
  | 'model_general'
  | 'error'

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
  selected_skill?: string | null
  workflow_summary?: string | null
  fallback_triggered?: boolean | null
  stop_reason?: string | null
  source_count?: number | null
  dominant_source_ratio?: number | null
  multi_source_coverage?: number | null
  clarification_needed?: boolean | null
  compare_result?: Record<string, unknown> | null
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

async function readErrorPayload(
  response: Response,
  fallback: string,
): Promise<{ message: string; code?: string }> {
  const errorData = await response.json().catch(() => ({}))
  if (typeof errorData.detail === 'string') {
    return { message: errorData.detail }
  }
  if (errorData.detail && typeof errorData.detail === 'object') {
    return {
      message: errorData.detail.message || fallback,
      code: errorData.detail.code,
    }
  }
  return { message: fallback }
}

export async function createSessionApi(): Promise<CreateSessionResponse> {
  const response = await apiFetch('/api/qa/sessions', { method: 'POST' })
  if (!response.ok) {
    const error = await readErrorPayload(response, '创建会话失败')
    throw new QaApiError(error.message, error.code)
  }
  return response.json()
}

export async function getSessionsApi(): Promise<QASessionListResponse> {
  const response = await apiFetch('/api/qa/sessions')
  if (!response.ok) {
    const error = await readErrorPayload(response, '获取会话列表失败')
    throw new QaApiError(error.message, error.code)
  }
  return response.json()
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

  const response = await apiFetch('/api/qa/ask', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })

  if (!response.ok) {
    const error = await readErrorPayload(response, '提问失败')
    throw new QaApiError(error.message, error.code)
  }
  return response.json()
}

export async function ingestFileApi(data: IngestFileRequest): Promise<IndexStatusResponse> {
  const response = await apiFetch('/api/qa/ingest/file', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  if (!response.ok) {
    const error = await readErrorPayload(response, '索引失败')
    throw new QaApiError(error.message, error.code)
  }
  return response.json()
}

export async function getFileIndexStatusApi(fileId: number): Promise<IndexStatusResponse> {
  const response = await apiFetch(`/api/qa/files/${fileId}/index-status`)
  if (!response.ok) {
    const error = await readErrorPayload(response, '获取索引状态失败')
    throw new QaApiError(error.message, error.code)
  }
  return response.json()
}

export async function getSessionMessagesApi(sessionId: number): Promise<QASessionMessagesResponse> {
  const response = await apiFetch(`/api/qa/sessions/${sessionId}/messages`)
  if (!response.ok) {
    const error = await readErrorPayload(response, '获取会话消息失败')
    throw new QaApiError(error.message, error.code)
  }
  return response.json()
}

export async function deleteSessionApi(sessionId: number): Promise<{ message: string }> {
  const response = await apiFetch(`/api/qa/sessions/${sessionId}`, { method: 'DELETE' })
  if (!response.ok) {
    const error = await readErrorPayload(response, '删除会话失败')
    throw new QaApiError(error.message, error.code)
  }
  return response.json()
}
