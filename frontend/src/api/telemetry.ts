import { request } from '@/utils/request'
import type { TelemetryPoint } from '@/types'

export function listTelemetry(): Promise<TelemetryPoint[]> {
  return request<TelemetryPoint[]>({ url: '/telemetry' })
}
