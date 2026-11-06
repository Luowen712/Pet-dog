import { request } from '@/utils/request'

export interface SendCommandResult {
  seq: number
  action: number
  accepted: boolean
}

/** 发动作：POST /api/commands/send { action: 0x33 } */
export function sendCommand(action: number): Promise<SendCommandResult> {
  return request<SendCommandResult>({
    url: '/commands/send',
    method: 'post',
    data: { action },
  })
}
