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
