import { request } from '@/utils/request'
import type { LoginResult, User } from '@/types'

export function login(username: string, password: string): Promise<LoginResult> {
  return request<LoginResult>({
    url: '/auth/login',
    method: 'post',
    data: { username, password },
  })
}

/**
 * 注册：只建账号、不签发 token，成功后前端切回登录页。
 * 契约见 docs/contracts/openapi.yaml /api/auth/register。
 */
export function register(username: string, password: string): Promise<User> {
  return request<User>({
    url: '/auth/register',
    method: 'post',
    data: { username, password },
  })
}

export function fetchMe(): Promise<User> {
  return request<User>({ url: '/auth/me' })
}

/** 登出全部会话：后端 tv+1，所有设备上的旧 token 立即失效 */
export function logoutAll(): Promise<{ logged_out: true }> {
  return request({ url: '/auth/logout', method: 'post' })
}

export function changePassword(
  oldPassword: string,
  newPassword: string,
): Promise<{ reauth_required: true }> {
  return request({
    url: '/auth/password',
    method: 'put',
    data: { old_password: oldPassword, new_password: newPassword },
  })
}

export function deleteAccount(
  password: string,
  confirmUsername: string,
): Promise<{ status: 'revoking' }> {
  return request({
    url: '/auth/account',
    method: 'delete',
    data: { password, confirm_username: confirmUsername },
  })
}
