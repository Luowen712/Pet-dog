/** 后端统一返回体外壳：{ code, message, data, timestamp } */
export interface ApiResponse<T> {
  code: number
  message: string
  data: T
  timestamp: number
}

export interface User {
  id: number
  username: string
  name: string
  role: string
}

export interface LoginResult {
  token: string
  user: User
}

export type BindingState = 'claimable' | 'bound' | 'retired'

export type ControlState =
  | 'unconfigured'
  | 'offline'
  | 'ready'
  | 'busy'
  | 'recovery_required'
  | 'handover_required'
  | 'faulted'

export interface Device {
  id: number
  name: string
  online: boolean
  firmware: string
  last_heartbeat: string | null
  battery: number | null
  location?: string
  binding_state: BindingState
  control_state: ControlState
  supported_actions: number[]
}

export interface ClaimableDevice {
  id: number
  name: string
}

export interface DeviceStatus {
  device_id: number
  online: boolean
  control_state: ControlState
  session_id: string | null
  state_revision: number
  battery: number | null
  voltage: number | null
  action: number | null
  face: number | null
  music_state: number | null
  track: number | null
  volume: number | null
  weather_code: number | null
  temp: number | null
  updated_at: string
}

export type CommandStatus =
  | 'pending'
  | 'accepted'
  | 'done'
  | 'rejected'
  | 'unknown'
  | 'superseded'
  | 'legacy_unmapped'

export type TransportStatus = 'ok' | 'write_failed' | 'partial_write'

/** GET /api/commands/{id} 的返回体：命令是有生命周期实体，终态只由后端判定 */
export interface CommandReceipt {
  cmd_id: string
  device_id: number
  action: number
  seq: number | null
  status: CommandStatus
  transport: TransportStatus | null
  reason: string | null
  error_code: number | null
  revision: number
  created_at: string
  updated_at: string
  finished_at: string | null
}

export interface FaceItem {
  id: number
  name: string
  builtin: boolean
  preview?: string | null
}

export interface AckData {
  cmd_id?: string
  seq: number
  status: 'OK' | 'ERROR'
  cost_ms: number
}

/** 已关闭页面的历史类型：代码保留，路由与导航不再暴露 */
export type CommandState = 'OK' | 'TIMEOUT' | 'ERROR' | 'PENDING'

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

export interface WeatherInfo {
  code: number
  text: string
  temp: number
  updated_at: string
  location?: string
  source?: string
}

export interface StateData {
  device_id?: number
  online?: boolean
  control_state?: ControlState
  session_id?: string | null
  state_revision?: number
  battery: number | null
  voltage: number | null
  action: number | null
  face: number | null
  music_state?: number | null
  track?: number | null
  volume?: number | null
  weather_code?: number | null
  temp?: number | null
}

export interface LinkData {
  device_id: number
  online: boolean
  control_state: ControlState
  reason: string | null
  session_id: string | null
  state_revision: number
}

export interface PingData {
  server_time: string
}

/** 音乐/天气本期关闭，事件类型保留给隐藏组件编译 */
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
  | { event: 'command'; data: CommandReceipt }
  | { event: 'ack'; data: AckData }
  | { event: 'link'; data: LinkData }
  | { event: 'ping'; data: PingData }
  | { event: 'music'; data: MusicData }
  | { event: 'weather'; data: WeatherData }

export type WsEventName = WsEvent['event']
