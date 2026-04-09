/**
 * 未配置时默认 `/api`：与 Vite `server.proxy['/api']`、Dockerfile 中构建参数一致。
 * 若留空，原先会请求 `/auth/login`、`/files/...`，无法命中代理，表现为登录成功/失败异常或登录后接口 401。
 */
const API_BASE =
  (import.meta.env.VITE_API_BASE_URL || '').trim() || '/api'

/** 与 router 的 `createWebHistory(import.meta.env.BASE_URL)` 一致，避免子路径部署时跳错登录页 */
function loginHref(): string {
  const raw = import.meta.env.BASE_URL || '/'
  const base = raw.replace(/\/+$/, '') || ''
  return base ? `${base}/login` : '/login'
}

function isLoginPage(): boolean {
  const p = window.location.pathname.replace(/\/+$/, '') || '/'
  const login = loginHref().replace(/\/+$/, '') || '/login'
  return p === login
}

let unauthorizedHandling = false

function handleUnauthorized() {
  localStorage.removeItem('token')
  localStorage.removeItem('username')
  localStorage.removeItem('role')
  localStorage.removeItem('can_download')

  if (isLoginPage() || unauthorizedHandling) {
    return
  }
  unauthorizedHandling = true
  window.alert('登录状态已失效，请重新登录')
  window.location.href = loginHref()
}

export async function apiFetch(
  path: string,
  init: RequestInit = {},
): Promise<Response> {
  const headers = new Headers(init.headers ?? {})
  const token = localStorage.getItem('token')?.trim()

  if (token) {
    headers.set('Authorization', `Bearer ${token}`)
  }

  const url = `${API_BASE}${path}`
  let response: Response
  try {
    response = await fetch(url, {
      ...init,
      headers,
    })
  } catch (error) {
    throw toNetworkError(error, url)
  }

  if (response.status === 401) {
    handleUnauthorized()
  }

  return response
}

export function getApiBase(): string {
  return API_BASE
}

export function toNetworkError(error: unknown, url: string): Error {
  const fallback =
    `网络请求失败，未能连接到 ${url}。请检查前端 API 地址、Vite 代理、后端服务和浏览器控制台中的 CORS/连接错误。`
  if (error instanceof Error) {
    const detail = error.message?.trim()
    return new Error(detail ? `${fallback} 原始错误：${detail}` : fallback)
  }
  return new Error(fallback)
}

/** FastAPI: detail 可能是 string | ValidationError[] | { message, code } */
export function formatApiErrorDetail(detail: unknown): string {
  if (detail == null) return ''
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    return detail
      .map((item) => {
        if (item && typeof item === 'object' && 'msg' in item) {
          return String((item as { msg: unknown }).msg)
        }
        return JSON.stringify(item)
      })
      .join('; ')
  }
  if (typeof detail === 'object') {
    const o = detail as Record<string, unknown>
    if (typeof o.message === 'string' && o.message.trim()) return o.message
    return JSON.stringify(detail)
  }
  return String(detail)
}

export function parseHttpErrorPayload(
  bodyText: string,
  httpStatus: number,
  fallback: string,
): { message: string; code?: string } {
  const statusBit = `HTTP ${httpStatus}`
  const trimmed = bodyText.trim()
  if (!trimmed) {
    return { message: `${fallback}（${statusBit}）` }
  }
  try {
    const body = JSON.parse(trimmed) as { detail?: unknown }
    const d = body.detail
    if (d && typeof d === 'object' && !Array.isArray(d)) {
      const rec = d as Record<string, unknown>
      if (typeof rec.message === 'string' && rec.message.trim()) {
        return {
          message: rec.message,
          code: typeof rec.code === 'string' ? rec.code : undefined,
        }
      }
    }
    const fromDetail = formatApiErrorDetail(d)
    if (fromDetail) return { message: fromDetail }
  } catch {
    /* 非 JSON */
  }
  const snip = trimmed.length > 400 ? `${trimmed.slice(0, 400)}…` : trimmed
  return { message: `${fallback}（${statusBit}）：${snip}` }
}

export async function readApiErrorMessage(
  response: Response,
  fallback: string,
): Promise<string> {
  const text = await response.text().catch(() => '')
  return parseHttpErrorPayload(text, response.status, fallback).message
}

/** 读取响应体一次：失败时抛出带可读文案的 Error；成功时解析 JSON。 */
export async function readJsonOk<T>(response: Response, errorFallback: string): Promise<T> {
  const text = await response.text()
  if (!response.ok) {
    throw new Error(parseHttpErrorPayload(text, response.status, errorFallback).message)
  }
  if (!text.trim()) {
    return undefined as T
  }
  try {
    return JSON.parse(text) as T
  } catch {
    throw new Error(`${errorFallback}：响应不是合法 JSON`)
  }
}
