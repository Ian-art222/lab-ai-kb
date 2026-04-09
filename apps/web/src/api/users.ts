import { apiFetch, readJsonOk } from './client'

export interface UserItem {
  id: number
  username: string
  role: 'root' | 'admin' | 'member'
  is_active: boolean
  can_download: boolean
  created_at: string
  updated_at: string
  last_login_at?: string | null
}

export interface UserCreatePayload {
  username: string
  password: string
  role: 'root' | 'admin' | 'member'
  is_active: boolean
  can_download?: boolean
}

export interface UserUpdatePayload {
  username?: string
  role?: 'root' | 'admin' | 'member'
  can_download?: boolean
}

export async function getMeApi(): Promise<UserItem> {
  const response = await apiFetch('/users/me')
  return readJsonOk<UserItem>(response, '获取当前用户信息失败')
}

export async function getUsersApi(q?: string): Promise<UserItem[]> {
  const query = q ? `?q=${encodeURIComponent(q)}` : ''
  const response = await apiFetch(`/users${query}`)
  return readJsonOk<UserItem[]>(response, '获取用户列表失败')
}

export async function createUserApi(payload: UserCreatePayload): Promise<UserItem> {
  const response = await apiFetch('/users', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  return readJsonOk<UserItem>(response, '创建用户失败')
}

export async function updateUserApi(userId: number, payload: UserUpdatePayload): Promise<UserItem> {
  const response = await apiFetch(`/users/${userId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  return readJsonOk<UserItem>(response, '更新用户失败')
}

export async function updateUserStatusApi(userId: number, isActive: boolean): Promise<UserItem> {
  const response = await apiFetch(`/users/${userId}/status`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ is_active: isActive }),
  })
  return readJsonOk<UserItem>(response, '更新用户状态失败')
}

export async function resetUserPasswordApi(userId: number, newPassword: string): Promise<void> {
  const response = await apiFetch(`/users/${userId}/reset-password`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ new_password: newPassword }),
  })
  await readJsonOk<{ message?: string }>(response, '重置密码失败')
}
