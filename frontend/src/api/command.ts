import { request } from '@/utils/request'
import { ApiError } from '@/utils/errors'
import type { CommandReceipt, CommandStatus, TransportStatus } from '@/types'

export interface SendCommandResult {
  /** 命令主键（后端生成）：pending 表以它为准，断线重连后用它查 /commands/{id} 对账 */
  cmd_id: string
  seq: number
  action: number
  accepted: boolean
  /** 受理时恒为 pending */
  status: CommandStatus
  /** 串口写入结果，前端不展示 */
  transport: TransportStatus
}

/** 发动作：POST /api/commands/send { action: 0x33 } */
export function sendCommand(action: number): Promise<SendCommandResult> {
  return request<SendCommandResult>({
    url: '/commands/send',
    method: 'post',
    data: { action },
  })
}

/**
 * 查一条命令的真实状态：GET /api/commands/{id}
 *
 * 只用于断线重连后的对账，不要轮询。记录不存在时后端返回 code 40400 而不是 HTTP 404，
 * 所以这里用 silent 跳过统一 toast —— 记录被清理不是错误，对不上就当命令已终结。
 */
export async function getCommand(cmdId: string): Promise<CommandReceipt | null> {
  try {
    return await request<CommandReceipt | null>(
      { url: `/commands/${encodeURIComponent(cmdId)}`, method: 'get' },
      { silent: true },
    )
  } catch (error) {
    // 契约：记录不存在是 code 40400 + data null，不是 HTTP 404
    if (error instanceof ApiError && error.code === 40400) return null
    throw error
  }
}
