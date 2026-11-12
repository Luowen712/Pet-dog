import type { User } from '@/types'

const TOKEN_KEY = 'petdog_token'
const USER_KEY = 'petdog_user'
const DEVICE_KEY = 'petdog_device'

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
  localStorage.removeItem(DEVICE_KEY)
}

export function getStoredDeviceId(): number {
  return Number(localStorage.getItem(DEVICE_KEY) ?? '1') || 1
}

export function setStoredDeviceId(id: number): void {
  localStorage.setItem(DEVICE_KEY, String(id))
}
