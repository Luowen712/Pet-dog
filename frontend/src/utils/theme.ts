import { readonly, ref } from 'vue'

export type ThemeId = 'porcelain' | 'phosphor'
export type BurstTone = 'accent' | 'oled'

export interface ParticleBurstDetail {
  x: number
  y: number
  count: number
  tone: BurstTone
}

const STORAGE_KEY = 'petdog_theme'
const BURST_EVENT = 'petdog:particle-burst'

const THEME_META_COLOR: Record<ThemeId, string> = {
  porcelain: '#ebe5d9',
  phosphor: '#071014',
}

const currentTheme = ref<ThemeId>('porcelain')
let initialized = false

function readStoredTheme(): ThemeId {
  try {
    const saved = localStorage.getItem(STORAGE_KEY)
    if (saved === 'porcelain' || saved === 'phosphor') return saved
  } catch {
    // 忽略受限存储环境
  }
  return 'porcelain'
}

function applyThemeToDom(id: ThemeId): void {
  if (typeof document === 'undefined') return
  document.documentElement.dataset.theme = id
  const meta = document.querySelector('meta[name="theme-color"]')
  if (meta) meta.setAttribute('content', THEME_META_COLOR[id])
}

export function initTheme(): ThemeId {
  if (!initialized) {
    initialized = true
    currentTheme.value = readStoredTheme()
  }
  applyThemeToDom(currentTheme.value)
  return currentTheme.value
}

export function setTheme(id: ThemeId): void {
  currentTheme.value = id
  initialized = true
  applyThemeToDom(id)
  try {
    localStorage.setItem(STORAGE_KEY, id)
  } catch {
    // 忽略受限存储环境
  }
}

export function toggleTheme(): void {
  setTheme(currentTheme.value === 'porcelain' ? 'phosphor' : 'porcelain')
}

export function useTheme() {
  initTheme()
  return {
    theme: readonly(currentTheme),
    setTheme,
    toggleTheme,
  }
}

export function emitParticleBurst(
  x: number,
  y: number,
  tone: BurstTone = 'accent',
  count = 16,
): void {
  if (typeof window === 'undefined') return
  window.dispatchEvent(
    new CustomEvent<ParticleBurstDetail>(BURST_EVENT, {
      detail: { x, y, count, tone },
    }),
  )
}

export function onParticleBurst(handler: (detail: ParticleBurstDetail) => void): () => void {
  if (typeof window === 'undefined') return () => {}
  const listener = (event: Event) => {
    const custom = event as CustomEvent<ParticleBurstDetail>
    if (custom.detail) handler(custom.detail)
  }
  window.addEventListener(BURST_EVENT, listener)
  return () => window.removeEventListener(BURST_EVENT, listener)
}
