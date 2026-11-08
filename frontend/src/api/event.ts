import { request } from '@/utils/request'

export interface WsTicket {
  ticket: string
  /** 有效期秒数，契约固定 30 */
  expires_in_sec: number
}

/**
 * 换一次性 WebSocket 票据：POST /api/events/ticket { device_id: 1 }
 *
 * 浏览器 new WebSocket() 不能自定义请求头，JWT 只能塞 URL，而 URL 会进 access log、
 * 浏览器历史和抓包工具。所以先用带 Bearer 的普通 HTTP 换一张 30 秒、只能用一次的票据。
 */
export function fetchWsTicket(deviceId: number): Promise<WsTicket> {
  return request<WsTicket>({
    url: '/events/ticket',
    method: 'post',
    data: { device_id: deviceId },
  })
}
