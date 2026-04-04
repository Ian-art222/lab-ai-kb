const API_BASE = (import.meta.env.VITE_API_BASE_URL || '').trim()

function handleUnauthorized() {
  localStorage.removeItem('token')
  localStorage.removeItem('username')
  localStorage.removeItem('role')

  if (window.location.pathname !== '/login') {
    window.alert('登录状态已失效，请重新登录')
    window.location.href = '/login'
  }
}

export async function apiFetch(
  path: string,
  init: RequestInit = {},
): Promise<Response> {
  const headers = new Headers(init.headers ?? {})
  const token = localStorage.getItem('token')

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
