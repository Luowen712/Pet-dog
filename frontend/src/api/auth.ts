import { request } from '@/utils/request'
import type { LoginResult, User } from '@/types'

export function login(username: string, password: string): Promise<LoginResult> {
  return request<LoginResult>({
    url: '/auth/login',
    method: 'post',
    data: { username, password },
  })
}

export function fetchMe(): Promise<User> {
  return request<User>({ url: '/auth/me' })
}
