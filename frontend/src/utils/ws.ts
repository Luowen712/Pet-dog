import type { WsEvent } from '@/types'
import { runtime } from '@/mock/runtime'
import { fetchWsTicket } from '@/api/event'
import { ApiError } from '@/utils/errors'

export type SocketStatus = 'connecting' | 'open' | 'closed'

export interface SocketOptions {
  deviceId: number
  onEvent: (event: WsEvent) => void
  onStatus: (status: SocketStatus) => void
  /** 服务端关闭码：1004 身份失效，1008 设备归属丢失，4009 连接数超限 */
  onClose: (code: number, message?: string) => void
}

const USE_MOCK = import.meta.env.VITE_USE_MOCK === 'true'

/** 75 秒一个事件都没有，只可能是死连接（服务端每 30 秒至少会有一次 ping） */
const SILENCE_MS = 75000

/**
 * /ws/device 客户端。
 *
 * 三件事和契约绑定：
 * 1. JWT 不进 URL —— 先 POST /api/events/ticket 换一张 30 秒、一次性的票据，票据随 URL 走；
 * 2. 每次建连（含重连）都要重新取票，旧票用过即废；
 * 3. 关闭码决定下一步：1000 不重连；1004 回登录；1008 清设备；4003 重新取票；
 *    4009 停止自动重试；1001/1011 按 1→2→4→8→10 秒退避。
 */
export class DeviceSocket {
  private options: SocketOptions
  private ws: WebSocket | null = null
  private retry = 0
  private timer: number | null = null
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
    if (!this.options.deviceId) {
      this.options.onStatus('closed')
      return
    }
    this.closed = false
    this.clearReconnect()
    this.options.onStatus('connecting')

    let ticket = ''
    try {
      ticket = (await fetchWsTicket(this.options.deviceId)).ticket
    } catch (error) {
      if (this.closed) return
      this.options.onStatus('closed')
      if (error instanceof ApiError && error.code === 40400) {
        // 设备不可见/已解绑：停止重连，交给调用方清设备
        this.closed = true
        this.options.onClose(1008)
        return
      }
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
    this.mockOff?.()
    this.mockOff = null
    this.ws?.close(1000)
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
      this.options.onEvent({
        event: 'link',
        data: {
          device_id: this.options.deviceId,
          online: true,
          control_state: 'ready',
          reason: null,
          session_id: 'mock',
          state_revision: 1,
        },
      })
      this.options.onEvent({
        event: 'state',
        data: {
          battery: 88,
          voltage: 3.9,
          action: 49,
          face: 0,
          music_state: null,
          track: null,
          volume: null,
          weather_code: null,
          temp: null,
        },
      })
    }, 320)
  }

  /** 关闭码语义见 docs/plan/06 §5 */
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
        // 用户主动关闭/页面卸载，不要重连
        this.closed = true
        return
      case 1004:
        // 身份失效：换账号、改密、登出全部会话
        this.closed = true
        this.options.onClose(1004)
        return
      case 1008:
        // 设备被解绑或归属丢失：只清设备，保留登录
        this.closed = true
        this.options.onClose(1008)
        return
      case 4003:
        // 票据无效/过期/已用：重新取票
        this.scheduleReconnect(0)
        return
      case 4009:
        this.closed = true
        this.options.onClose(4009, '该设备已在其他窗口打开，最多同时 3 个连接')
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
