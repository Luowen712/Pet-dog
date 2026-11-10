import { request } from '@/utils/request'
import type { LoginResult, User } from '@/types'

export interface RegisterResult {
  username: string
  name: string
}

export function login(username: string, password: string): Promise<LoginResult> {
  return request<LoginResult>({
    url: '/auth/login',
    method: 'post',
    data: { username, password },
  })
}

/**
 * 注册：只建账号、不签发 token，成功后前端切回登录页。
 * 契约见 docs/contracts/http-api.md §3.3。
 */
export function register(username: string, password: string): Promise<RegisterResult> {
  return request<RegisterResult>({
    url: '/auth/register',
    method: 'post',
    data: { username, password },
  })
}

export function fetchMe(): Promise<User> {
  return request<User>({ url: '/auth/me' })
}
