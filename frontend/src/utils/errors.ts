/** 业务错误：HTTP 200 但返回体 code !== 0，或后端统一错误信封（401/403/429/500）时抛出 */
export class ApiError extends Error {
  code: number
  reason?: string | null
  retryAfter?: number | null

  constructor(
    code: number,
    message: string,
    extra?: { reason?: string | null; retryAfter?: number | null },
  ) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.reason = extra?.reason ?? null
    this.retryAfter = extra?.retryAfter ?? null
  }
}

export const ERROR_TEXT: Record<number, string> = {
  40000: '请求参数有误',
  40001: '用户名或密码错误',
  40002: '参数不合法',
  40100: '登录已过期',
  40101: '登录已过期',
  40400: '接口不存在',
  40300: '没有权限',
  40900: '操作冲突，请稍后重试',
  42900: '请求过于频繁，请稍后再试',
  50000: '服务内部错误',
}
