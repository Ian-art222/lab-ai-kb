import { apiFetch } from './client'

export interface SettingItem {
  system_name: string
  lab_name: string
  llm_provider: string
  llm_api_base: string
  llm_api_key_masked: string
  llm_api_key_configured: boolean
  llm_model: string
  embedding_provider: string
  embedding_api_base: string
  embedding_api_key_masked: string
  embedding_api_key_configured: boolean
  embedding_model: string
  embedding_batch_size?: number | null
  embedding_effective_batch_size: number
  qa_enabled: boolean
  sidebar_auto_collapse: boolean
  theme_mode: string
  last_llm_test_success?: boolean | null
  last_llm_test_at?: string | null
  last_llm_test_detail?: string | null
  last_embedding_test_success?: boolean | null
  last_embedding_test_at?: string | null
  last_embedding_test_detail?: string | null
  updated_at: string
}

export interface SettingStatus {
  qa_enabled: boolean
  llm_provider: string
  llm_model: string
  llm_configured: boolean
  embedding_provider: string
  embedding_model: string
  embedding_configured: boolean
  embedding_batch_size?: number | null
  embedding_effective_batch_size: number
  current_chat_standard: string
  current_index_standard: string
  indexed_files_count: number
  index_standard_mismatch: boolean
  index_standard_mismatch_count: number
  sidebar_auto_collapse: boolean
  theme_mode: string
  last_llm_test_success?: boolean | null
  last_llm_test_at?: string | null
  last_llm_test_detail?: string | null
  last_embedding_test_success?: boolean | null
  last_embedding_test_at?: string | null
  last_embedding_test_detail?: string | null
}

export interface ConnectionTestResult {
  ok: boolean
  service: string
  detail: string
}

export interface SettingUpdatePayload {
  system_name: string
  lab_name: string
  llm_provider: string
  llm_api_base: string
  llm_api_key?: string | null
  llm_model: string
  embedding_provider: string
  embedding_api_base: string
  embedding_api_key?: string | null
  embedding_model: string
  embedding_batch_size?: number | null
  qa_enabled: boolean
  sidebar_auto_collapse: boolean
  theme_mode: string
}

async function readError(response: Response, fallback: string): Promise<string> {
  const data = await response.json().catch(() => ({}))
  return data.detail || fallback
}

export async function getSettingsApi(): Promise<SettingItem> {
  const response = await apiFetch('/api/settings')
  if (!response.ok) throw new Error(await readError(response, '获取系统设置失败'))
  return response.json()
}

export async function updateSettingsApi(payload: SettingUpdatePayload): Promise<SettingItem> {
  const response = await apiFetch('/api/settings', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!response.ok) throw new Error(await readError(response, '保存系统设置失败'))
  return response.json()
}

export async function getSettingsStatusApi(): Promise<SettingStatus> {
  const response = await apiFetch('/api/settings/status')
  if (!response.ok) throw new Error(await readError(response, '获取配置状态失败'))
  return response.json()
}

export async function testEmbeddingConnectionApi(payload: {
  provider: string
  api_base: string
  api_key: string
  model: string
}): Promise<ConnectionTestResult> {
  const response = await apiFetch('/api/settings/test/embedding', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!response.ok) throw new Error(await readError(response, 'Embedding 测试失败'))
  return response.json()
}

export async function testLlmConnectionApi(payload: {
  provider: string
  api_base: string
  api_key: string
  model: string
}): Promise<ConnectionTestResult> {
  const response = await apiFetch('/api/settings/test/llm', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!response.ok) throw new Error(await readError(response, 'LLM 测试失败'))
  return response.json()
}
