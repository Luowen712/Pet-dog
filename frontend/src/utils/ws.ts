import type { WsEvent } from '@/types'
import { runtime } from '@/mock/runtime'
import { getToken } from './session'

export type SocketStatus = 'connecting' | 'open' | 'closed'

export interface SocketOptions {
  deviceId: number
  onEvent: (event: WsEvent) => void
  onStatus: (status: SocketStatus) => void
}

const USE_MOCK = import.meta.env.VITE_USE_MOCK === 'true'

/**
 * /ws/device 客户端：断线指数退避重连 1 → 2 → 4 → 8 → 10 秒封顶。
 * 要点有两个：同一时间只允许一个重连定时器；主动 close 之后不再重连。
 */
export class DeviceSocket {
  private options: SocketOptions
  private ws: WebSocket | null = null
  private retry = 0
  private timer: number | null = null
  private heartbeat: number | null = null
  private closed = false
  private mockOff: (() => void) | null = null

  constructor(options: SocketOptions) {
    this.options = options
  }

  connect(): void {
    this.closed = false
    if (USE_MOCK) {
      this.connectMock()
      return
    }
    this.options.onStatus('connecting')
    const ws = new WebSocket(this.buildUrl())
    this.ws = ws
    ws.onopen = () => {
      this.retry = 0
      this.options.onStatus('open')
    }
    ws.onmessage = (event) => this.handleMessage(event.data)
    ws.onerror = () => ws.close()
    ws.onclose = () => {
      this.options.onStatus('closed')
      if (!this.closed) this.scheduleReconnect()
    }
  }

  close(): void {
    this.closed = true
    if (this.timer !== null) {
      window.clearTimeout(this.timer)
      this.timer = null
    }
    if (this.heartbeat !== null) {
      window.clearInterval(this.heartbeat)
      this.heartbeat = null
    }
    this.mockOff?.()
    this.mockOff = null
    this.ws?.close()
    this.ws = null
    this.options.onStatus('closed')
  }

  private connectMock(): void {
    this.options.onStatus('connecting')
    window.setTimeout(() => {
      if (this.closed) return
      this.options.onStatus('open')
      this.mockOff = runtime.subscribe((event) => this.options.onEvent(event))
      this.options.onEvent({ event: 'link', data: { online: true } })
      this.heartbeat = window.setInterval(() => {
        if (!this.closed) this.options.onEvent({ event: 'state', data: runtime.snapshot() })
      }, 8000)
    }, 320)
  }

  private handleMessage(raw: unknown): void {
    if (typeof raw !== 'string') return
    try {
      const parsed = JSON.parse(raw) as WsEvent
      if (parsed && typeof parsed.event === 'string') this.options.onEvent(parsed)
    } catch {
      // 后端偶尔会发空帧/二进制帧，忽略即可，别让一条坏消息打断整条连接
    }
  }

  private buildUrl(): string {
    const token = encodeURIComponent(getToken())
    const base = import.meta.env.VITE_WS_BASE
    if (base) {
      return `${base.replace(/\/$/, '')}/ws/device?token=${token}&device_id=${this.options.deviceId}`
    }
    const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws'
    return `${protocol}://${window.location.host}/ws/device?token=${token}&device_id=${this.options.deviceId}`
  }

  private scheduleReconnect(): void {
    if (this.timer !== null) return
    const seconds = Math.min(10, 2 ** this.retry)
    this.retry += 1
    this.timer = window.setTimeout(() => {
      this.timer = null
      if (!this.closed) this.connect()
    }, seconds * 1000)
  }
}
