import { getApiBase, parseHttpErrorPayload, toNetworkError } from './client'

export interface LoginPayload {
    username: string
    password: string
  }
  
  export interface LoginResponse {
    access_token: string
    token_type: string
    username: string
    role: string
    can_download: boolean
  }
  
  export async function loginApi(data: LoginPayload): Promise<LoginResponse> {
    const url = `${getApiBase()}/auth/login`
    let response: Response
    try {
      response = await fetch(url, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(data),
      })
    } catch (error) {
      throw toNetworkError(error, url)
    }
  
    const text = await response.text()
    if (!response.ok) {
      throw new Error(parseHttpErrorPayload(text, response.status, '登录失败').message)
    }
    try {
      return JSON.parse(text) as LoginResponse
    } catch {
      throw new Error('登录失败：响应不是合法 JSON')
    }
  }