import type { User } from '@/types'

const TOKEN_KEY = 'petdog_token'
const USER_KEY = 'petdog_user'

/** 当前选中设备按账号分开存：A 选的设备不能带到 B 的页面 */
const DEVICE_KEY_PREFIX = 'petdog_device_'

/** 断线重连后用于对账的 cmd_id，按账号 + 设备隔离，最多 20 条 */
const PENDING_KEY_PREFIX = 'petdog_pending_'

export interface PendingRef {
  cmd_id: string
  action: number
}

export function getToken(): string {
  return localStorage.getItem(TOKEN_KEY) ?? ''
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token)
}

export function getStoredUser(): User | null {
  const raw = localStorage.getItem(USER_KEY)
  if (!raw) return null
  try {
    return JSON.parse(raw) as User
  } catch {
    return null
  }
}

export function setStoredUser(user: User): void {
  localStorage.setItem(USER_KEY, JSON.stringify(user))
}

export function clearSession(): void {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(USER_KEY)
}

export function getStoredDeviceId(uid: number | null): number | null {
  if (!uid) return null
  const raw = localStorage.getItem(`${DEVICE_KEY_PREFIX}${uid}`)
  const id = Number(raw)
  return Number.isInteger(id) && id > 0 ? id : null
}

export function setStoredDeviceId(uid: number | null, id: number): void {
  if (!uid) return
  localStorage.setItem(`${DEVICE_KEY_PREFIX}${uid}`, String(id))
}

export function clearStoredDeviceId(uid: number | null): void {
  if (!uid) return
  localStorage.removeItem(`${DEVICE_KEY_PREFIX}${uid}`)
  clearStoredPending(uid)
}

export function clearStoredPending(uid: number | null): void {
  if (!uid) return
  const prefix = `${PENDING_KEY_PREFIX}${uid}_`
  for (const key of Object.keys(localStorage)) {
    if (key.startsWith(prefix)) localStorage.removeItem(key)
  }
}

export function getStoredPending(uid: number | null, deviceId: number): PendingRef[] {
  if (!uid || !deviceId) return []
  const raw = localStorage.getItem(`${PENDING_KEY_PREFIX}${uid}_${deviceId}`)
  if (!raw) return []
  try {
    const parsed = JSON.parse(raw) as PendingRef[]
    return Array.isArray(parsed) ? parsed.slice(0, 20) : []
  } catch {
    return []
  }
}

export function setStoredPending(
  uid: number | null,
  deviceId: number,
  items: PendingRef[],
): void {
  if (!uid || !deviceId) return
  const key = `${PENDING_KEY_PREFIX}${uid}_${deviceId}`
  if (items.length === 0) {
    localStorage.removeItem(key)
    return
  }
  localStorage.setItem(key, JSON.stringify(items.slice(0, 20)))
}
