import { request } from '@/utils/request'
import { ApiError } from '@/utils/errors'
import type { CommandReceipt } from '@/types'

/**
 * 提交动作：POST /api/commands/send
 *
 * cmd_id 由前端生成，放在 Idempotency-Key 头里，和返回的 cmd_id 是同一个 UUID。
 * 网络失败后用同一个 key 重试，后端同键同体返回原单，不会重复动作。
 */
export function sendCommand(
  deviceId: number,
  action: number,
  cmdId: string,
): Promise<CommandReceipt> {
  return request<CommandReceipt>({
    url: '/commands/send',
    method: 'post',
    headers: { 'Idempotency-Key': cmdId },
    data: { device_id: deviceId, action },
  })
}

/**
 * 查一条命令的真实状态：GET /api/commands/{id}
 *
 * 只用于断线重连后的对账。记录不存在时后端返回 code 40400 而不是 HTTP 404，
 * 所以这里 silent；记录被清理不代表失败，只代表查不到。
 */
export async function getCommand(cmdId: string): Promise<CommandReceipt | null> {
  try {
    return await request<CommandReceipt | null>(
      { url: `/commands/${encodeURIComponent(cmdId)}`, method: 'get' },
      { silent: true },
    )
  } catch (error) {
    if (error instanceof ApiError && error.code === 40400) return null
    throw error
  }
}
