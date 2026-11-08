import type { WsEvent } from '@/types'
import { runtime } from '@/mock/runtime'
import { fetchWsTicket } from '@/api/event'

export type SocketStatus = 'connecting' | 'open' | 'closed'

export interface SocketOptions {
  deviceId: number
  onEvent: (event: WsEvent) => void
  onStatus: (status: SocketStatus) => void
  /** 不可恢复的关闭（票据/鉴权失败），调用方负责提示用户 */
  onFatal?: (message: string) => void
}

const USE_MOCK = import.meta.env.VITE_USE_MOCK === 'true'

/** 75 秒一个事件都没有，只可能是死连接（服务端每 30 秒至少会有一次活动） */
const SILENCE_MS = 75000

/**
 * /ws/device 客户端。
 *
 * 三件事和契约绑定：
 * 1. JWT 不进 URL —— 先 POST /api/events/ticket 换一张 30 秒、一次性的票据，票据随 URL 走；
 * 2. 每次建连（含重连）都要重新取票，旧票用过即废；
 * 3. 关闭码决定下一步：1000/4001 不重连，4003 重新取票，4009 退避 5 秒，
 *    1011 或异常断开按 1 → 2 → 4 → 8 → 10 秒退避。
 */
export class DeviceSocket {
  private options: SocketOptions
  private ws: WebSocket | null = null
  private retry = 0
  private timer: number | null = null
  private heartbeat: number | null = null
  private watchdog: number | null = null
  private closed = false
  /** 自己主动断开（看门狗超时/传输错误），不是服务端正常关闭 */
  private stale = false
  private mockOff: (() => void) | null = null

  constructor(options: SocketOptions) {
    this.options = options
  }

  /** 建连：先换票再开 socket，票据拿不到就按重连流程退避 */
  async connect(): Promise<void> {
    this.closed = false
    this.clearReconnect()
    this.options.onStatus('connecting')

    let ticket = ''
    try {
      ticket = (await fetchWsTicket(this.options.deviceId)).ticket
    } catch {
      if (this.closed) return
      this.options.onStatus('closed')
      this.scheduleReconnect()
      return
    }
    if (this.closed) return

    if (USE_MOCK) {
      this.connectMock()
      return
    }
    this.openSocket(ticket)
  }

  close(): void {
    this.closed = true
    this.clearReconnect()
    this.stopWatchdog()
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

  private openSocket(ticket: string): void {
    const ws = new WebSocket(this.buildUrl(ticket))
    this.ws = ws
    ws.onopen = () => {
      this.retry = 0
      this.touchWatchdog()
      this.options.onStatus('open')
    }
    ws.onmessage = (event) => {
      this.touchWatchdog()
      this.handleMessage(event.data)
    }
    ws.onerror = () => {
      this.stale = true
      ws.close()
    }
    ws.onclose = (event) => this.handleClose(event.code)
  }

  private connectMock(): void {
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

  /** 关闭码语义见 docs/contracts/events.md §1.3 */
  private handleClose(code: number): void {
    this.stopWatchdog()
    this.ws = null
    this.options.onStatus('closed')
    if (this.closed) return

    if (this.stale) {
      this.stale = false
      this.scheduleReconnect()
      return
    }
    switch (code) {
      case 1000:
        // 服务端正常收工，不要无限重连
        this.closed = true
        return
      case 4001:
        this.closed = true
        this.options.onFatal?.('实时连接鉴权失败，请重新登录')
        return
      case 4003:
        // 票据无效/过期/已用：connect() 本来就会重新取票
        this.scheduleReconnect(1)
        return
      case 4009:
        this.scheduleReconnect(5)
        return
      default:
        this.scheduleReconnect()
    }
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

  private buildUrl(ticket: string): string {
    const suffix = `/ws/device?device_id=${this.options.deviceId}&ticket=${encodeURIComponent(ticket)}`
    const base = import.meta.env.VITE_WS_BASE
    if (base) return `${base.replace(/\/$/, '')}${suffix}`
    const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws'
    return `${protocol}://${window.location.host}${suffix}`
  }

  private touchWatchdog(): void {
    this.stopWatchdog()
    this.watchdog = window.setTimeout(() => {
      this.watchdog = null
      if (this.closed) return
      // 静默 75 秒：主动断开，让 onclose 走重连
      this.stale = true
      this.ws?.close()
    }, SILENCE_MS)
  }

  private stopWatchdog(): void {
    if (this.watchdog !== null) {
      window.clearTimeout(this.watchdog)
      this.watchdog = null
    }
  }

  private clearReconnect(): void {
    if (this.timer !== null) {
      window.clearTimeout(this.timer)
      this.timer = null
    }
  }

  private scheduleReconnect(fixedSeconds?: number): void {
    if (this.timer !== null || this.closed) return
    const seconds = fixedSeconds ?? Math.min(10, 2 ** this.retry)
    this.retry += 1
    this.timer = window.setTimeout(() => {
      this.timer = null
      if (!this.closed) void this.connect()
    }, seconds * 1000)
  }
}
