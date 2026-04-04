import { getApiBase, toNetworkError } from './client'

export interface LoginPayload {
    username: string
    password: string
  }
  
  export interface LoginResponse {
    access_token: string
    token_type: string
    username: string
    role: string
  }
  
  export async function loginApi(data: LoginPayload): Promise<LoginResponse> {
    const url = `${getApiBase()}/api/auth/login`
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
  
    if (!response.ok) {
      const errorData = await response.json()
      throw new Error(errorData.detail || '登录失败')
    }
  
    return response.json()
  }