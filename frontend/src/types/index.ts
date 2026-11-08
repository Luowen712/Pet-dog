/** 后端统一返回体外壳：{ code, message, data, timestamp } */
export interface ApiResponse<T> {
  code: number
  message: string
  data: T
  timestamp: number
}

export interface User {
  username: string
  name: string
  role: string
}

export interface LoginResult {
  token: string
  user: User
}

export interface Device {
  id: number
  name: string
  online: boolean
  firmware: string
  last_heartbeat: string
  battery: number
  location?: string
}

export interface DeviceStatus {
  device_id: number
  battery: number
  voltage: number
  action: number
  face: number
  music_state: number
  track: number
  volume: number
  weather_code: number
  temp: number
  updated_at: string
}

export type CommandState = 'OK' | 'TIMEOUT' | 'ERROR' | 'PENDING'

export type CommandStatus =
  | 'pending'
  | 'accepted'
  | 'done'
  | 'rejected'
  | 'unknown'
  | 'superseded'

export type TransportStatus = 'ok' | 'write_failed' | 'partial_write'

/** GET /api/commands/{id} 的返回体：命令是有生命周期实体，终态只由后端判定 */
export interface CommandReceipt {
  cmd_id: string
  device_id: number
  action: number
  seq?: number
  status: CommandStatus
  transport: TransportStatus
  error_code?: number | null
  created_at: string
  updated_at: string
  finished_at?: string | null
}

export interface CommandLog {
  id: number
  device_id: number
  time: string
  action: number
  action_name: string
  status: CommandState
  cost_ms: number
  seq: number
  response: string
}

export interface PageResult<T> {
  items: T[]
  total: number
  page: number
  size: number
}

export interface TelemetryPoint {
  time: string
  battery: number
  voltage: number
}

export interface SceneStep {
  action: number
}

export interface Scene {
  id: number
  name: string
  description: string
  steps: SceneStep[]
  updated_at: string
}

export interface FaceItem {
  id: number
  name: string
  builtin: boolean
  preview?: string
}

export interface WeatherInfo {
  code: number
  text: string
  temp: number
  updated_at: string
}

export interface AckData {
  /** 后端补上的命令主键；0x81 帧只带 1 字节 seq，映射表 30 秒后作废，此时可能缺失 */
  cmd_id?: string
  seq: number
  status: 'OK' | 'ERROR'
  cost_ms: number
}

export interface StateData {
  battery: number
  voltage: number
  action: number
  face: number
  music_state: number
  track: number
  weather_code: number
  temp: number
}

export interface LinkData {
  online: boolean
}

export interface MusicData {
  state: number
  track: number
  volume?: number
}

export interface WeatherData {
  code: number
  text: string
  temp: number
}

export type WsEvent =
  | { event: 'state'; data: StateData }
  | { event: 'ack'; data: AckData }
  | { event: 'link'; data: LinkData }
  | { event: 'music'; data: MusicData }
  | { event: 'weather'; data: WeatherData }

export type WsEventName = WsEvent['event']
