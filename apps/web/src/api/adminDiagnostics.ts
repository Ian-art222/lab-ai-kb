import { apiFetch } from './client'

export type TraceItem = {
  trace_id: string
  request_id?: string | null
  session_id: number
  question: string
  normalized_query?: string | null
  rewritten_queries?: string[] | null
  retrieval_strategy?: string | null
  selected_evidence?: Array<Record<string, unknown>> | null
  evidence_bundles?: Record<string, unknown> | null
  strict_mode?: boolean | null
  is_abstained: boolean
  abstain_reason?: string | null
  failed: boolean
  failure_reason?: string | null
  model_name?: string | null
  token_usage?: Record<string, unknown> | null
  latency_ms?: number | null
  latency_breakdown?: Record<string, unknown> | null
  task_type?: string | null
  selected_scope?: string | null
  selected_skill?: string | null
  planner_meta?: Record<string, unknown> | null
  workflow_steps?: Array<Record<string, unknown>> | null
  tool_traces?: Array<Record<string, unknown>> | null
  guardrail_events?: Array<Record<string, unknown>> | null
  fallback_triggered?: boolean | null
  retrieval_rounds?: number | null
  stop_reason?: string | null
  source_count?: number | null
  dominant_source_ratio?: number | null
  multi_source_coverage?: number | null
  compare_result?: Record<string, unknown> | null
  clarification_needed?: boolean | null
  created_at: string
}

export type TraceListResponse = {
  total: number
  limit: number
  offset: number
  items: TraceItem[]
}

export type TraceDetail = TraceItem & {
  filters?: Record<string, unknown> | null
  debug_json?: Record<string, unknown> | null
  source_file_ids?: number[]
}

export type ReasonStatsItem = {
  reason_code: string
  count: number
}

function errorDetail(payload: unknown, fallback: string): string {
  if (payload && typeof payload === 'object' && 'detail' in payload) {
    const detail = (payload as { detail?: unknown }).detail
    if (typeof detail === 'string') return detail
    if (detail && typeof detail === 'object' && 'message' in detail) {
      const message = (detail as { message?: unknown }).message
      if (typeof message === 'string') return message
    }
  }
  return fallback
}

export async function getDiagnosticsTracesApi(params: Record<string, unknown>): Promise<TraceListResponse> {
  const q = new URLSearchParams()
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && `${v}`.trim() !== '') q.set(k, String(v))
  })

  const response = await apiFetch(`/api/admin/diagnostics/traces?${q.toString()}`)
  const payload = (await response.json()) as unknown
  if (!response.ok) throw new Error(errorDetail(payload, '加载诊断列表失败'))
  return payload as TraceListResponse
}

export async function getDiagnosticsTraceDetailApi(traceId: string): Promise<TraceDetail> {
  const response = await apiFetch(`/api/admin/diagnostics/traces/${encodeURIComponent(traceId)}`)
  const payload = (await response.json()) as unknown
  if (!response.ok) throw new Error(errorDetail(payload, '加载 Trace 详情失败'))
  return payload as TraceDetail
}

export async function retryIndexFileApi(fileId: number, forceReindex = false): Promise<void> {
  const response = await apiFetch(
    `/api/admin/diagnostics/files/${fileId}/retry-index?force_reindex=${forceReindex ? 'true' : 'false'}`,
    { method: 'POST' },
  )
  const payload = (await response.json()) as unknown
  if (!response.ok) throw new Error(errorDetail(payload, '重试索引失败'))
}

export async function getReasonStatsApi(): Promise<ReasonStatsItem[]> {
  const response = await apiFetch('/api/admin/diagnostics/traces/stats/reasons')
  const payload = (await response.json()) as unknown
  if (!response.ok) throw new Error(errorDetail(payload, '加载 reason 统计失败'))
  return payload as ReasonStatsItem[]
}

export async function exportTraceApi(traceId: string): Promise<Record<string, unknown>> {
  const response = await apiFetch(`/api/admin/diagnostics/traces/${encodeURIComponent(traceId)}/export`)
  const payload = (await response.json()) as unknown
  if (!response.ok) throw new Error(errorDetail(payload, '导出 trace 失败'))
  return payload as Record<string, unknown>
}
