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
 * 注册：接口路径文档里没定死，暂按 /auth/register 写。
 * 好在这条只需两头对上，后端 /docs 一出来改这里一处就行。
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
