import { request } from '@/utils/request'
import type { CommandLog, PageResult } from '@/types'

export interface LogQuery {
  page: number
  size: number
  status?: string
  device_id?: number
}

export function listLogs(params: LogQuery): Promise<PageResult<CommandLog>> {
  return request<PageResult<CommandLog>>({ url: '/logs', params })
}
