const WEEK = ['SUN', 'MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT']

export function pad2(n: number): string {
  return String(n).padStart(2, '0')
}

export function formatClock(date: Date = new Date()): string {
  return `${pad2(date.getHours())}:${pad2(date.getMinutes())}:${pad2(date.getSeconds())}`
}

export function formatDateLabel(date: Date = new Date()): string {
  return `${pad2(date.getMonth() + 1)}-${pad2(date.getDate())} ${WEEK[date.getDay()]}`
}

export function formatDateTime(input?: string | number | Date): string {
  if (!input) return '--'
  const date = new Date(input)
  if (Number.isNaN(date.getTime())) return String(input)
  return `${date.getFullYear()}-${pad2(date.getMonth() + 1)}-${pad2(date.getDate())} ${pad2(date.getHours())}:${pad2(date.getMinutes())}:${pad2(date.getSeconds())}`
}

export function formatShortTime(input?: string | number | Date): string {
  if (!input) return '--'
  const date = new Date(input)
  if (Number.isNaN(date.getTime())) return String(input)
  return `${pad2(date.getHours())}:${pad2(date.getMinutes())}`
}

export function formatRelative(input?: string | number | Date): string {
  if (!input) return '--'
  const date = new Date(input)
  if (Number.isNaN(date.getTime())) return String(input)
  const diff = Date.now() - date.getTime()
  if (diff < 0) return '刚刚'
  const minute = Math.floor(diff / 60000)
  if (minute < 1) return '刚刚'
  if (minute < 60) return `${minute} 分钟前`
  const hour = Math.floor(minute / 60)
  if (hour < 24) return `${hour} 小时前`
  return `${Math.floor(hour / 24)} 天前`
}

export function formatTrack(track?: number): string {
  if (!track) return '----'
  return String(track).padStart(4, '0')
}

export function formatCost(ms?: number): string {
  if (typeof ms !== 'number' || Number.isNaN(ms)) return '--'
  return `${ms} ms`
}

export function formatBytes(size?: number): string {
  if (typeof size !== 'number') return '--'
  return `${size} B`
}

export type DeviceStatusTone = 'ok' | 'warn' | 'bad' | 'muted'

export interface DeviceStatusView {
  label: string
  tone: DeviceStatusTone
}

/** 仅呈现设备本身在线与工作状态（遵循 06 §12.1 优先级） */
export function describeDeviceStatus(opts: {
  online: boolean
  controlState?: string | null
}): DeviceStatusView {
  const { online, controlState } = opts
  if (controlState === 'faulted') return { label: '连接异常', tone: 'bad' }
  if (controlState === 'handover_required') return { label: '待交接', tone: 'warn' }
  if (!online || controlState === 'offline') return { label: '离线', tone: 'muted' }
  if (controlState === 'recovery_required') return { label: '在线 · 待恢复', tone: 'warn' }
  if (controlState === 'busy') return { label: '在线 · 执行中', tone: 'warn' }
  return { label: '在线', tone: 'ok' }
}
