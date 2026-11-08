/** 业务错误：HTTP 200 但返回体 code !== 0 时抛出 */
export class ApiError extends Error {
  code: number

  constructor(code: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.code = code
  }
}

export const ERROR_TEXT: Record<number, string> = {
  40001: '用户名或密码错误',
  40002: '参数不合法',
  40100: '登录已过期',
  40101: '登录已过期',
  40400: '接口不存在',
  40300: '没有权限',
  40900: '操作冲突，请稍后重试',
  50000: '服务内部错误',
}
