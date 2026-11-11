/**
 * 会话代次：登录 / 登出 / 切换账号时 +1。
 *
 * 作用：A 账号发出、B 账号登录后才回来的旧请求，不能覆盖 B 的页面，
 * 也不能用旧请求的 401 把 B 踢下线。request 层在发请求时记下代次，
 * 回来后发现代次变了就直接丢弃结果。
 */
let epoch = 0

export function currentEpoch(): number {
  return epoch
}

export function bumpEpoch(): number {
  epoch += 1
  return epoch
}
