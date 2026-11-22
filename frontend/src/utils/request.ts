import axios from 'axios'
import type { AxiosRequestConfig } from 'axios'
import { ElMessage } from 'element-plus'
import type { ApiResponse } from '@/types'
import { matchMock } from '@/mock'
import { ApiError } from './errors'
import { currentEpoch } from './epoch'
import { clearSession, getStoredUser, getToken } from './session'

const USE_MOCK = import.meta.env.VITE_USE_MOCK === 'true'

/** 会话已切换：调用方应静默丢弃，不要提示、不要改页面 */
export const STALE_SESSION_CODE = -2

export const http = axios.create({
  baseURL: import.meta.env.VITE_API_BASE ?? '/api',
  timeout: 10000,
})

http.interceptors.request.use((config) => {
  const token = getToken()
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

let redirecting = false

export async function handleUnauthorized(warningMessage = '登录已过期，请重新登录'): Promise<void> {
  if (redirecting) return
  redirecting = true
  const oldUid = getStoredUser()?.id ?? null
  try {
    const [{ default: router }, { useAuthStore }, { useDeviceStore }, { usePetStore }] =
      await Promise.all([
        import('@/router'),
        import('@/stores/auth'),
        import('@/stores/device'),
        import('@/stores/pet'),
      ])
    // 先清理 petStore（断开 WS 并按旧 uid 清本地 pending 缓存），再清 session 与 authStore
    usePetStore().reset(oldUid)
    clearSession()
    useAuthStore().reset()
    useDeviceStore().reset()
    if (router.currentRoute.value.path !== '/login') {
      ElMessage.warning(warningMessage)
      await router.replace({
        path: '/login',
        query: { redirect: router.currentRoute.value.fullPath },
      })
    }
  } finally {
    window.setTimeout(() => {
      redirecting = false
    }, 800)
  }
}

export interface RequestOptions {
  /** 静默模式：失败不弹 toast，由调用方自己处理（断线对账时命令记录可能已被清理） */
  silent?: boolean
}

/**
 * 统一请求入口：
 * 1. Mock 开启时先走内置假后端（后端未启动也能把页面跑起来）
 * 2. 拆掉 { code, message, data } 外壳，页面直接拿 data
 * 3. 401 清登录态跳登录页，其余错误统一 toast
 * 4. 发请求时记下会话代次，回来时代次变了就丢弃（A 的旧请求不能改 B 的页面）
 */
export async function request<T>(
  config: AxiosRequestConfig,
  options: RequestOptions = {},
): Promise<T> {
  const epoch = currentEpoch()

  try {
    if (USE_MOCK) {
      const mocked = await matchMock(config)
      if (mocked.matched) {
        if (epoch !== currentEpoch()) throw new ApiError(STALE_SESSION_CODE, '会话已切换')
        return mocked.data as T
      }
    }

    const response = await http.request<ApiResponse<T>>(config)
    if (epoch !== currentEpoch()) throw new ApiError(STALE_SESSION_CODE, '会话已切换')

    const body = response.data as ApiResponse<T> & {
      reason?: string | null
      retry_after?: number | null
    }
    if (body && typeof body === 'object' && typeof body.code === 'number') {
      if (body.code !== 0) {
        throw new ApiError(body.code, body.message || '请求失败', {
          reason: body.reason ?? null,
          retryAfter: body.retry_after ?? null,
        })
      }
      return body.data
    }
    return body as unknown as T
  } catch (error) {
    // 账号已经切换：旧请求的结果一律丢弃，不提示、不跳登录
    if (error instanceof ApiError && error.code === STALE_SESSION_CODE) throw error
    if (epoch !== currentEpoch()) throw new ApiError(STALE_SESSION_CODE, '会话已切换')

    if (error instanceof ApiError) {
      if (!options.silent) ElMessage.error(error.message)
      throw error
    }
    if (axios.isAxiosError(error)) {
      const status = error.response?.status
      const payload = error.response?.data as
        | { code?: number; message?: string; reason?: string | null; retry_after?: number | null }
        | undefined
      const bodyCode = typeof payload?.code === 'number' ? payload.code : undefined
      const retryAfter =
        typeof payload?.retry_after === 'number' ? payload.retry_after : null
      const reason = typeof payload?.reason === 'string' ? payload.reason : null

      if (status === 401) {
        await handleUnauthorized()
        throw new ApiError(bodyCode ?? 40101, payload?.message || '登录已过期', { reason })
      }
      if (bodyCode !== undefined) {
        const msg =
          bodyCode === 42900 && retryAfter
            ? `${payload?.message || '请求过于频繁'}（${retryAfter}s 后重试）`
            : payload?.message || `请求失败（HTTP ${status}）`
        if (!options.silent) ElMessage.error(msg)
        throw new ApiError(bodyCode, msg, { reason, retryAfter })
      }
      const message = status ? `请求失败（HTTP ${status}）` : '网络异常，请检查后端服务是否已启动'
      if (!options.silent) ElMessage.error(message)
      throw new ApiError(status ?? -1, message)
    }
    if (!options.silent) ElMessage.error('请求失败')
    throw error
  }
}
