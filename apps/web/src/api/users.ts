import { apiFetch } from './client'

export interface UserItem {
  id: number
  username: string
  role: 'admin' | 'member'
  is_active: boolean
  created_at: string
  updated_at: string
  last_login_at?: string | null
}

export interface UserCreatePayload {
  username: string
  password: string
  role: 'admin' | 'member'
  is_active: boolean
}

export interface UserUpdatePayload {
  username: string
  role: 'admin' | 'member'
}

async function readError(response: Response, fallback: string): Promise<string> {
  const data = await response.json().catch(() => ({}))
  return data.detail || fallback
}

export async function getUsersApi(q?: string): Promise<UserItem[]> {
  const query = q ? `?q=${encodeURIComponent(q)}` : ''
  const response = await apiFetch(`/api/users${query}`)
  if (!response.ok) throw new Error(await readError(response, '获取用户列表失败'))
  return response.json()
}

export async function createUserApi(payload: UserCreatePayload): Promise<UserItem> {
  const response = await apiFetch('/api/users', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!response.ok) throw new Error(await readError(response, '创建用户失败'))
  return response.json()
}

export async function updateUserApi(userId: number, payload: UserUpdatePayload): Promise<UserItem> {
  const response = await apiFetch(`/api/users/${userId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!response.ok) throw new Error(await readError(response, '更新用户失败'))
  return response.json()
}

export async function updateUserStatusApi(userId: number, isActive: boolean): Promise<UserItem> {
  const response = await apiFetch(`/api/users/${userId}/status`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ is_active: isActive }),
  })
  if (!response.ok) throw new Error(await readError(response, '更新用户状态失败'))
  return response.json()
}

export async function resetUserPasswordApi(userId: number, newPassword: string): Promise<void> {
  const response = await apiFetch(`/api/users/${userId}/reset-password`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ new_password: newPassword }),
  })
  if (!response.ok) throw new Error(await readError(response, '重置密码失败'))
}
