import type { AxiosRequestConfig } from 'axios'
import type {
  CommandLog,
  CommandState,
  Device,
  FaceItem,
  PageResult,
  Scene,
  TelemetryPoint,
  WeatherInfo,
} from '@/types'
import { ACTIONS, actionName } from '@/constants/actions'
import { FACES } from '@/constants/faces'
import { WEATHER_LOCATION, WEATHER_MAP, weatherCodeFromWmo } from '@/constants/weather'
import { ApiError } from '@/utils/errors'
import { runtime } from './runtime'

export type MockHit = { matched: false } | { matched: true; data: unknown }

const now = (): number => Date.now()
const iso = (offsetMs = 0): string => new Date(now() + offsetMs).toISOString()
const delay = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms))

function hit(data: unknown): MockHit {
  return { matched: true, data }
}

function pathOf(config: AxiosRequestConfig): string {
  const raw = config.url ?? ''
  return raw
    .replace(/^https?:\/\/[^/]+/, '')
    .replace(/^\/api(?=\/|$)/, '')
    .split('?')[0]
}

function bodyOf(config: AxiosRequestConfig): Record<string, unknown> {
  const data = config.data as unknown
  if (!data) return {}
  if (typeof data === 'string') {
    try {
      return JSON.parse(data) as Record<string, unknown>
    } catch {
      return {}
    }
  }
  if (typeof data === 'object') return data as Record<string, unknown>
  return {}
}

/* ------------------------------- 假数据 ------------------------------- */

const devices: Device[] = [
  {
    id: 1,
    name: '桌宠一号 · 小灰',
    online: true,
    firmware: 'v2.0.0',
    last_heartbeat: iso(-8000),
    battery: 78,
    location: '书桌',
  },
  {
    id: 2,
    name: '桌宠二号 · 小白',
    online: false,
    firmware: 'v1.9.3',
    last_heartbeat: iso(-2 * 60 * 60 * 1000),
    battery: 41,
    location: '客厅',
  },
]

function freshDevice(device: Device): Device {
  if (!device.online) return { ...device }
  return { ...device, last_heartbeat: iso(-Math.floor(Math.random() * 20000)) }
}

/* 改名后刷新页面也要记住，先存在 localStorage 里，后端上线后以服务端为准 */
const MOCK_DEVICE_NAMES_KEY = 'petdog_mock_device_names'

function readDeviceNames(): Record<string, string> {
  try {
    const raw = localStorage.getItem(MOCK_DEVICE_NAMES_KEY)
    return raw ? (JSON.parse(raw) as Record<string, string>) : {}
  } catch {
    return {}
  }
}

function saveDeviceName(id: number, name: string): void {
  const names = readDeviceNames()
  names[String(id)] = name
  localStorage.setItem(MOCK_DEVICE_NAMES_KEY, JSON.stringify(names))
}

function applyDeviceNames(): void {
  const names = readDeviceNames()
  devices.forEach((device) => {
    const saved = names[String(device.id)]
    if (saved) device.name = saved
  })
}

applyDeviceNames()

const STATUS_POOL: CommandState[] = ['OK', 'OK', 'OK', 'OK', 'TIMEOUT', 'ERROR']

const logs: CommandLog[] = Array.from({ length: 57 }, (_, index) => {
  const action = ACTIONS[(index * 7) % ACTIONS.length]
  const status = STATUS_POOL[index % STATUS_POOL.length]
  const isTimeout = status === 'TIMEOUT'
  return {
    id: 1000 - index,
    device_id: index % 3 === 0 ? 2 : 1,
    time: iso(-index * 97_000),
    action: action.code,
    action_name: action.name,
    status,
    cost_ms: isTimeout ? 3000 : 80 + ((index * 37) % 720),
    seq: (index % 200) + 1,
    response: isTimeout ? '3 s 内无应答' : status === 'ERROR' ? '0x05 执行失败' : '0x81 受理 / 0x02 完成',
  }
})

const faces: FaceItem[] = FACES.map((face) => ({ id: face.id, name: face.name, builtin: true }))
let faceAutoId = 100

const scenes: Scene[] = [
  {
    id: 1,
    name: '早上好',
    description: '起床三连，适合演示开场',
    steps: [{ action: 0x31 }, { action: 0x43 }, { action: 0x40 }],
    updated_at: iso(-86400000),
  },
  {
    id: 2,
    name: '巡游',
    description: '走两步转个身再回来',
    steps: [{ action: 0x33 }, { action: 0x35 }, { action: 0x33 }, { action: 0x36 }],
    updated_at: iso(-3 * 86400000),
  },
  {
    id: 3,
    name: '睡觉',
    description: '趴下关灯，收工',
    steps: [{ action: 0x32 }, { action: 0x45 }],
    updated_at: iso(-5 * 86400000),
  },
]
let sceneAutoId = 10

const telemetry: TelemetryPoint[] = Array.from({ length: 24 }, (_, index) => {
  const battery = Math.round(72 + 12 * Math.sin(index / 3.4) + ((index * 5) % 7))
  return {
    time: iso(-(23 - index) * 3600 * 1000),
    battery,
    voltage: Number((3.68 + battery * 0.0045).toFixed(2)),
  }
})

const weather: WeatherInfo = {
  code: 0,
  text: '晴',
  temp: 23,
  updated_at: iso(),
  location: WEATHER_LOCATION.name,
  source: 'Mock',
}

const WEATHER_CACHE_KEY = 'petdog_weather_cache'
const WEATHER_TTL = 10 * 60 * 1000

function readWeatherCache(): WeatherInfo | null {
  try {
    const raw = localStorage.getItem(WEATHER_CACHE_KEY)
    if (!raw) return null
    const info = JSON.parse(raw) as WeatherInfo
    const age = now() - new Date(info.updated_at).getTime()
    return age >= 0 && age < WEATHER_TTL ? info : null
  } catch {
    return null
  }
}

/**
 * 开发期没有后端，Mock 直接抓 Open-Meteo（免 key、允许跨域）。
 * 正式环境这段应搬回后端：每 10 分钟抓一次、缓存，再通过 /api/weather 和 WS 推给前端。
 */
async function fetchLiveWeather(): Promise<WeatherInfo | null> {
  const cached = readWeatherCache()
  if (cached) return cached
  // jsdom 测试环境不发外网请求
  if (import.meta.env.MODE === 'test') return null

  const controller = new AbortController()
  const timer = window.setTimeout(() => controller.abort(), 6000)
  try {
    const query = new URLSearchParams({
      latitude: String(WEATHER_LOCATION.latitude),
      longitude: String(WEATHER_LOCATION.longitude),
      current: 'temperature_2m,weather_code',
      timezone: WEATHER_LOCATION.timezone,
    })
    const response = await fetch(`https://api.open-meteo.com/v1/forecast?${query}`, {
      signal: controller.signal,
    })
    if (!response.ok) return null

    const data = (await response.json()) as {
      current?: { temperature_2m?: number; weather_code?: number }
    }
    const wmo = Number(data.current?.weather_code)
    const temp = Number(data.current?.temperature_2m)
    if (!Number.isFinite(wmo) || !Number.isFinite(temp)) return null

    const code = weatherCodeFromWmo(wmo)
    const info: WeatherInfo = {
      code,
      text: WEATHER_MAP[code]?.text ?? '未知',
      temp: Math.round(temp),
      updated_at: new Date().toISOString(),
      location: WEATHER_LOCATION.name,
      source: 'Open-Meteo',
    }
    localStorage.setItem(WEATHER_CACHE_KEY, JSON.stringify(info))
    return info
  } catch {
    // 断网、被墙、超时都退回静态兜底，不要让页面卡住
    return null
  } finally {
    window.clearTimeout(timer)
  }
}

/* ---------------------------- 假账号（本地） ---------------------------- */

const MOCK_USERS_KEY = 'petdog_mock_users'
const MOCK_SESSION_KEY = 'petdog_mock_session'

interface MockUser {
  username: string
  password: string
  name: string
}

function readUsers(): MockUser[] {
  try {
    const raw = localStorage.getItem(MOCK_USERS_KEY)
    return raw ? (JSON.parse(raw) as MockUser[]) : []
  } catch {
    return []
  }
}

function writeUsers(users: MockUser[]): void {
  localStorage.setItem(MOCK_USERS_KEY, JSON.stringify(users))
}

function readSession(): { username: string; name: string; role: string } | null {
  try {
    const raw = localStorage.getItem(MOCK_SESSION_KEY)
    return raw ? (JSON.parse(raw) as { username: string; name: string; role: string }) : null
  } catch {
    return null
  }
}

function saveSession(session: { username: string; name: string; role: string }): void {
  localStorage.setItem(MOCK_SESSION_KEY, JSON.stringify(session))
}

/* ------------------------------- 路由 ------------------------------- */

export async function matchMock(config: AxiosRequestConfig): Promise<MockHit> {
  const path = pathOf(config)
  const method = (config.method ?? 'get').toLowerCase()
  const params = (config.params ?? {}) as Record<string, unknown>
  const body = bodyOf(config)

  if (method === 'get' && path === '/health') {
    return hit({ status: 'ok', mode: 'mock' })
  }

  /* 认证 */
  if (method === 'post' && path === '/auth/login') {
    await delay(320)
    const username = String(body.username ?? '')
    const password = String(body.password ?? '')
    const isAdmin = username === 'admin' && password === '123456'
    const account = readUsers().find((user) => user.username === username && user.password === password)

    if (!isAdmin && !account) {
      throw new ApiError(40001, '用户名或密码错误')
    }

    const session = isAdmin
      ? { username: 'admin', name: '管理员', role: 'admin' }
      : { username: account!.username, name: account!.name, role: 'user' }
    saveSession(session)

    return hit({ token: `mock.${username}.${now()}`, user: session })
  }

  if (method === 'post' && path === '/auth/register') {
    await delay(320)
    const username = String(body.username ?? '').trim()
    const password = String(body.password ?? '')

    if (!/^[a-zA-Z0-9_\u4e00-\u9fa5]{3,20}$/.test(username)) {
      throw new ApiError(40002, '用户名需 3–20 位字母、数字、下划线或中文')
    }
    if (password.length < 6) {
      throw new ApiError(40002, '密码至少 6 位')
    }
    if (username === 'admin' || readUsers().some((user) => user.username === username)) {
      throw new ApiError(40900, '用户名已存在')
    }

    const account: MockUser = { username, password, name: username }
    writeUsers([...readUsers(), account])
    return hit({ username: account.username, name: account.name })
  }

  if (method === 'get' && path === '/auth/me') {
    return hit(readSession() ?? { username: 'admin', name: '管理员', role: 'admin' })
  }

  /* 设备 */
  if (method === 'get' && path === '/devices') {
    return hit(devices.map(freshDevice))
  }

  const statusMatch = path.match(/^\/devices\/(\d+)\/status$/)
  if (method === 'get' && statusMatch) {
    return hit({
      device_id: Number(statusMatch[1]),
      battery: runtime.battery,
      voltage: runtime.voltage,
      action: runtime.action,
      face: runtime.face,
      music_state: runtime.musicState,
      track: runtime.track,
      volume: runtime.volume,
      weather_code: weather.code,
      temp: weather.temp,
      updated_at: iso(),
    })
  }

  const deviceMatch = path.match(/^\/devices\/(\d+)$/)
  if (method === 'get' && deviceMatch) {
    const device = devices.find((item) => item.id === Number(deviceMatch[1]))
    if (!device) throw new ApiError(40400, '设备不存在')
    return hit(freshDevice(device))
  }

  // 改名：接口契约里还没定义，先按 PATCH /devices/{id} { name } 写
  if (method === 'patch' && deviceMatch) {
    const device = devices.find((item) => item.id === Number(deviceMatch[1]))
    if (!device) throw new ApiError(40400, '设备不存在')
    const name = String(body.name ?? '').trim()
    if (name.length < 1 || name.length > 20) {
      throw new ApiError(40002, '名字需要 1–20 个字符')
    }
    device.name = name
    saveDeviceName(device.id, name)
    return hit(freshDevice(device))
  }

  /* 指令 */
  if (method === 'post' && path === '/commands/send') {
    const action = Number(body.action)
    if (!Number.isFinite(action)) throw new ApiError(40002, '动作码不合法')
    const seq = runtime.nextSeq()
    const startedAt = now()
    runtime.action = action

    const log: CommandLog = {
      id: ++logAutoId,
      device_id: 1,
      time: iso(),
      action,
      action_name: actionName(action),
      status: 'PENDING',
      cost_ms: 0,
      seq,
      response: '等待设备应答',
    }
    logs.unshift(log)

    setTimeout(() => {
      const cost = now() - startedAt
      log.status = 'OK'
      log.cost_ms = cost
      log.response = '0x81 受理 / 0x02 完成'
      runtime.emit({ event: 'ack', data: { seq, status: 'OK', cost_ms: cost } })
      runtime.emit({ event: 'state', data: runtime.snapshot() })
    }, 520 + Math.floor(Math.random() * 620))

    runtime.emit({ event: 'state', data: runtime.snapshot() })
    return hit({ seq, action, accepted: true })
  }

  /* 音乐 */
  const musicMatch = path.match(/^\/devices\/(\d+)\/music$/)
  if (method === 'post' && musicMatch) {
    const command = Number(body.command)
    const value = Number(body.value ?? 0)
    if (command === 1) runtime.musicState = 1
    if (command === 0) runtime.musicState = 0
    if (command === 2) runtime.musicState = runtime.musicState === 2 ? 1 : 2
    if (command === 3) {
      runtime.track = (runtime.track % 9) + 1
      runtime.musicState = 1
    }
    if (command === 4) {
      runtime.track = ((runtime.track + 7) % 9) + 1
      runtime.musicState = 1
    }
    if (command === 5) runtime.volume = Math.min(30, Math.max(0, value))
    runtime.emit({
      event: 'music',
      data: { state: runtime.musicState, track: runtime.track, volume: runtime.volume },
    })
    return hit({ ok: true, state: runtime.musicState, track: runtime.track, volume: runtime.volume })
  }

  /* 表情 */
  if (method === 'get' && path === '/faces') {
    return hit(faces.map((face) => ({ ...face })))
  }

  if (method === 'post' && path === '/faces/current') {
    const face = Number(body.face)
    runtime.face = face
    runtime.emit({ event: 'state', data: runtime.snapshot() })
    return hit({ face })
  }

  if (method === 'post' && path === '/faces') {
    const form = config.data as FormData | undefined
    const file = form?.get('file')
    if (!(file instanceof File)) throw new ApiError(40002, '没有拿到上传文件')
    if (file.size !== 512) throw new ApiError(40002, '图片必须正好 512 字节（128×32 单色位图）')
    const item: FaceItem = {
      id: ++faceAutoId,
      name: file.name.replace(/\.[^.]+$/, ''),
      builtin: false,
      preview: URL.createObjectURL(file),
    }
    faces.push(item)
    return hit(item)
  }

  const faceMatch = path.match(/^\/faces\/(\d+)$/)
  if (method === 'delete' && faceMatch) {
    const id = Number(faceMatch[1])
    const index = faces.findIndex((face) => face.id === id)
    if (index < 0) throw new ApiError(40400, '表情不存在')
    if (faces[index].builtin) throw new ApiError(40002, '内置表情不能删除')
    faces.splice(index, 1)
    return hit({ ok: true })
  }

  /* 日志 */
  if (method === 'get' && path === '/logs') {
    const page = Math.max(1, Number(params.page ?? 1))
    const size = Math.max(1, Number(params.size ?? 10))
    const status = String(params.status ?? 'ALL')
    const deviceId = params.device_id ? Number(params.device_id) : undefined
    let filtered = logs
    if (status !== 'ALL') filtered = filtered.filter((log) => log.status === status)
    if (deviceId) filtered = filtered.filter((log) => log.device_id === deviceId)
    const start = (page - 1) * size
    const result: PageResult<CommandLog> = {
      items: filtered.slice(start, start + size),
      total: filtered.length,
      page,
      size,
    }
    return hit(result)
  }

  /* 遥测 */
  if (method === 'get' && path === '/telemetry') {
    return hit(telemetry.map((point) => ({ ...point })))
  }

  /* 天气 */
  if (method === 'get' && path === '/weather') {
    const live = await fetchLiveWeather()
    return hit(live ?? { ...weather, updated_at: iso() })
  }

  /* 场景 */
  if (method === 'get' && path === '/scenes') {
    return hit(scenes.map((scene) => ({ ...scene, steps: scene.steps.map((step) => ({ ...step })) })))
  }

  if (method === 'post' && path === '/scenes') {
    const name = String(body.name ?? '').trim()
    if (!name) throw new ApiError(40002, '场景名不能为空')
    const steps = Array.isArray(body.steps) ? (body.steps as Scene['steps']) : []
    const scene: Scene = {
      id: ++sceneAutoId,
      name,
      description: String(body.description ?? ''),
      steps: steps.map((step) => ({ action: Number(step.action) })),
      updated_at: iso(),
    }
    scenes.push(scene)
    return hit(scene)
  }

  const sceneMatch = path.match(/^\/scenes\/(\d+)$/)
  if (method === 'put' && sceneMatch) {
    const scene = scenes.find((item) => item.id === Number(sceneMatch[1]))
    if (!scene) throw new ApiError(40400, '场景不存在')
    if (typeof body.name === 'string') scene.name = body.name
    if (typeof body.description === 'string') scene.description = body.description
    if (Array.isArray(body.steps)) scene.steps = body.steps.map((step) => ({ action: Number(step.action) }))
    scene.updated_at = iso()
    return hit(scene)
  }

  if (method === 'delete' && sceneMatch) {
    const index = scenes.findIndex((item) => item.id === Number(sceneMatch[1]))
    if (index < 0) throw new ApiError(40400, '场景不存在')
    scenes.splice(index, 1)
    return hit({ ok: true })
  }

  const sceneRunMatch = path.match(/^\/scenes\/(\d+)\/run$/)
  if (method === 'post' && sceneRunMatch) {
    const scene = scenes.find((item) => item.id === Number(sceneRunMatch[1]))
    if (!scene) throw new ApiError(40400, '场景不存在')
    scene.steps.forEach((step, index) => {
      setTimeout(() => {
        runtime.action = step.action
        runtime.emit({ event: 'state', data: runtime.snapshot() })
      }, index * 900)
    })
    return hit({ ok: true, steps: scene.steps.length })
  }

  return { matched: false }
}

let logAutoId = 2000
