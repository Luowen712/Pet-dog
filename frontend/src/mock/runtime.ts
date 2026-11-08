import type { StateData, WsEvent } from '@/types'

type Listener = (event: WsEvent) => void

/**
 * Mock 后端共享的运行时状态。
 * 命令接口改它 → 定时 emit ack / state；MockSocket 订阅它 → 页面看起来像真的收到了推送。
 */
class MockRuntime {
  seq = 0
  battery = 78
  voltage = 3.92
  action = 0x31
  face = 0
  musicState = 0
  track = 3
  volume = 15

  private listeners = new Set<Listener>()

  subscribe(listener: Listener): () => void {
    this.listeners.add(listener)
    return () => {
      this.listeners.delete(listener)
    }
  }

  emit(event: WsEvent): void {
    this.listeners.forEach((listener) => listener(event))
  }

  /** 契约：seq 在 1-255 循环（0 保留），同一时刻不能有两条命令用同一个 seq */
  nextSeq(): number {
    this.seq = (this.seq % 255) + 1
    return this.seq
  }

  snapshot(): StateData {
    return {
      battery: this.battery,
      voltage: this.voltage,
      action: this.action,
      face: this.face,
      music_state: this.musicState,
      track: this.track,
      weather_code: 0,
      temp: 23,
    }
  }
}

export const runtime = new MockRuntime()
