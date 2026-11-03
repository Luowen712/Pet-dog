import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { ElMessage } from 'element-plus'
import type { AckData, StateData, WeatherInfo, WsEvent } from '@/types'
import { getDeviceStatus } from '@/api/device'
import { sendCommand } from '@/api/command'
import { sendMusic } from '@/api/music'
import { setCurrentFace } from '@/api/face'
import { getWeather } from '@/api/weather'
import { DeviceSocket } from '@/utils/ws'
import type { SocketStatus } from '@/utils/ws'

export type ButtonState = 'idle' | 'pending' | 'ok' | 'fail'

const TIMEOUT_MS = 3000

export const usePetStore = defineStore('pet', () => {
  const socketStatus = ref<SocketStatus>('closed')
  const online = ref(false)
  const battery = ref(0)
  const voltage = ref(0)
  const action = ref(0)
  const face = ref(0)
  const musicState = ref(0)
  const track = ref(0)
  const volume = ref(15)
  const weather = ref<WeatherInfo | null>(null)

  /** 每个动作码一个状态，不是全局一个 loading */
  const status = ref<Record<number, ButtonState>>({})
  /** seq → { action, timer }，ack 只按 seq 认领 */
  const pending = ref<Record<number, { action: number; timer: number }>>({})

  let socket: DeviceSocket | null = null

  const connected = computed(() => socketStatus.value === 'open')
  const musicLabel = computed(() => {
    if (musicState.value === 1) return '播放中'
    if (musicState.value === 2) return '已暂停'
    return '已停止'
  })

  function applyState(data: StateData): void {
    battery.value = data.battery
    voltage.value = data.voltage
    action.value = data.action
    face.value = data.face
    musicState.value = data.music_state
    if (typeof data.track === 'number' && data.track > 0) track.value = data.track
  }

  function onAck(data: AckData): void {
    const item = pending.value[data.seq]
    if (!item) return // 迟到的 ack 直接忽略
    window.clearTimeout(item.timer)
    delete pending.value[data.seq]
    status.value[item.action] = data.status === 'OK' ? 'ok' : 'fail'
    if (data.status !== 'OK') ElMessage.error('设备执行失败，请重试')
  }

  function onEvent(event: WsEvent): void {
    switch (event.event) {
      case 'state':
        applyState(event.data)
        break
      case 'ack':
        onAck(event.data)
        break
      case 'link':
        online.value = event.data.online
        break
      case 'music':
        musicState.value = event.data.state
        track.value = event.data.track
        if (typeof event.data.volume === 'number') volume.value = event.data.volume
        break
      case 'weather':
        weather.value = { ...event.data, updated_at: new Date().toISOString() }
        break
    }
  }

  function connect(deviceId: number): void {
    disconnect()
    socket = new DeviceSocket({
      deviceId,
      onEvent,
      onStatus: (value) => {
        socketStatus.value = value
      },
    })
    socket.connect()
    void loadSnapshot(deviceId)
    void loadWeather()
  }

  function disconnect(): void {
    socket?.close()
    socket = null
    socketStatus.value = 'closed'
  }

  async function loadSnapshot(deviceId: number): Promise<void> {
    try {
      const snapshot = await getDeviceStatus(deviceId)
      applyState({
        battery: snapshot.battery,
        voltage: snapshot.voltage,
        action: snapshot.action,
        face: snapshot.face,
        music_state: snapshot.music_state,
        track: snapshot.track,
        weather_code: snapshot.weather_code,
        temp: snapshot.temp,
      })
      volume.value = snapshot.volume
    } catch {
      // 统一错误提示已在 request 层弹过
    }
  }

  async function loadWeather(): Promise<void> {
    try {
      weather.value = await getWeather()
    } catch {
      // 天气失败不影响其它面板
    }
  }

  /** 发一个动作：立刻变黄，ack 回来变绿，3 秒没 ack 变红 */
  async function sendAction(code: number): Promise<void> {
    status.value[code] = 'pending'
    try {
      const { seq } = await sendCommand(code)
      const timer = window.setTimeout(() => {
        if (!pending.value[seq]) return
        delete pending.value[seq]
        status.value[code] = 'fail'
        ElMessage.error('设备无响应（3 秒超时），请检查蓝牙或串口连接')
      }, TIMEOUT_MS)
      pending.value[seq] = { action: code, timer }
      action.value = code
    } catch {
      status.value[code] = 'fail'
    }
  }

  async function controlMusic(command: number, value = 0, deviceId = 1): Promise<void> {
    try {
      await sendMusic(deviceId, command, value)
    } catch {
      // 已统一提示
    }
  }

  async function changeFace(id: number): Promise<void> {
    try {
      await setCurrentFace(id)
      face.value = id
    } catch {
      // 已统一提示
    }
  }

  function reset(): void {
    Object.values(pending.value).forEach((item) => window.clearTimeout(item.timer))
    pending.value = {}
    status.value = {}
    disconnect()
  }

  return {
    socketStatus,
    online,
    battery,
    voltage,
    action,
    face,
    musicState,
    track,
    volume,
    weather,
    status,
    pending,
    connected,
    musicLabel,
    connect,
    disconnect,
    loadSnapshot,
    loadWeather,
    sendAction,
    controlMusic,
    changeFace,
    reset,
  }
})
