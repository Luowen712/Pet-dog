import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { ElMessage } from 'element-plus'
import type {
  CommandReceipt,
  MusicData,
  StateData,
  WeatherData,
  WeatherInfo,
  WsEvent,
} from '@/types'
import { getDeviceStatus } from '@/api/device'
import { getCommand, sendCommand } from '@/api/command'
import { setCurrentFace } from '@/api/face'
import { sendMusic } from '@/api/music'
import { getWeather } from '@/api/weather'
import { DeviceSocket } from '@/utils/ws'
import type { SocketStatus } from '@/utils/ws'
import { ApiError } from '@/utils/errors'
import {
  clearStoredPending,
  getStoredPending,
  getStoredUser,
  setStoredPending,
} from '@/utils/session'

/** 按钮展示状态：只有 done 才允许变绿 */
export type ButtonState = 'idle' | 'pending' | 'accepted' | 'ok' | 'fail' | 'unknown'

/** 命令长时间没有任何回执，显示"结果不明"；它不是终态，后端如果后续 done 仍会纠正 */
const DISPLAY_TIMEOUT_MS = 8000
/** pending 映射的保留窗口，避免无限增长 */
const PENDING_RETIRE_MS = 60000
/** 一次对账最多查 20 条，契约明确要求不要无限查 */
const RECONCILE_MAX = 20

interface PendingCommand {
  cmd_id: string
  action: number
  seq: number | null
  timer: number
  expiry: number
  timedOut: boolean
}

function newCmdId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  // 兜底：RFC4122 v4 形状
  const bytes = new Uint8Array(16)
  crypto.getRandomValues(bytes)
  bytes[6] = (bytes[6] & 0x0f) | 0x40
  bytes[8] = (bytes[8] & 0x3f) | 0x80
  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, '0'))
  return `${hex.slice(0, 4).join('')}-${hex.slice(4, 6).join('')}-${hex
    .slice(6, 8)
    .join('')}-${hex.slice(8, 10).join('')}-${hex.slice(10, 16).join('')}`
}

export const usePetStore = defineStore('pet', () => {
  const socketStatus = ref<SocketStatus>('closed')
  const online = ref(false)
  const controlState = ref('unconfigured')
  const battery = ref<number | null>(null)
  const voltage = ref<number | null>(null)
  const action = ref<number | null>(null)
  const face = ref<number | null>(null)
  /** 音乐/天气本期关闭，字段保留给隐藏组件与旧事件处理器 */
  const weather = ref<WeatherInfo | null>(null)
  const musicState = ref(0)
  const track = ref(0)
  const volume = ref(15)

  /** 每个动作码一个状态，不是全局一个 loading */
  const status = ref<Record<number, ButtonState>>({})
  /** cmd_id → 命令。只有后端 done 才会变绿 */
  const pending = ref<Record<string, PendingCommand>>({})

  let socket: DeviceSocket | null = null
  /** 连接代次：切设备/重连/换账号都会 +1，异步回来的旧结果一律丢弃 */
  let generation = 0
  let currentDeviceId = 0
  let lastPingAt = 0
  /** 本次连接是否已经 open 过一次（首次 open 由 connect 里的 loadSnapshot 负责） */
  let openedOnce = false

  const connected = computed(() => socketStatus.value === 'open')
  const musicLabel = computed(() => {
    if (musicState.value === 1) return '播放中'
    if (musicState.value === 2) return '已暂停'
    return '已停止'
  })

  function uid(): number | null {
    return getStoredUser()?.id ?? null
  }

  function persistPending(): void {
    setStoredPending(
      uid(),
      currentDeviceId,
      Object.values(pending.value).map((item) => ({
        cmd_id: item.cmd_id,
        action: item.action,
      })),
    )
  }

  function clearTimers(item: PendingCommand): void {
    window.clearTimeout(item.timer)
    window.clearTimeout(item.expiry)
  }

  function armTimeout(item: PendingCommand): void {
    window.clearTimeout(item.timer)
    item.timer = window.setTimeout(() => {
      const live = pending.value[item.cmd_id]
      if (!live) return
      // 超时只表示"没拿到回执"，不能判失败；后端稍后推 done 仍会纠正
      live.timedOut = true
      status.value[live.action] = 'unknown'
      ElMessage.warning('结果不明：长时间没收到设备回执，重连后会再核对')
    }, DISPLAY_TIMEOUT_MS)
  }

  function dropPending(cmdId: string): void {
    const item = pending.value[cmdId]
    if (!item) return
    clearTimers(item)
    delete pending.value[cmdId]
    persistPending()
  }

  function addPending(cmdId: string, actionCode: number): PendingCommand {
    const item: PendingCommand = {
      cmd_id: cmdId,
      action: actionCode,
      seq: null,
      timer: 0,
      expiry: 0,
      timedOut: false,
    }
    armTimeout(item)
    item.expiry = window.setTimeout(() => {
      const live = pending.value[cmdId]
      if (!live) return
      if (!live.timedOut) status.value[live.action] = 'unknown'
      dropPending(cmdId)
    }, PENDING_RETIRE_MS)
    pending.value[cmdId] = item
    persistPending()
    return item
  }

  function applyState(data: StateData): void {
    online.value = data.online ?? online.value
    controlState.value = data.control_state ?? controlState.value
    battery.value = data.battery
    voltage.value = data.voltage
    action.value = data.action
    face.value = data.face
    if (typeof data.music_state === 'number') musicState.value = data.music_state
    if (typeof data.track === 'number' && data.track > 0) track.value = data.track
    if (typeof data.volume === 'number') volume.value = data.volume
  }

  function applyMusic(data: MusicData): void {
    musicState.value = data.state
    track.value = data.track
    if (typeof data.volume === 'number') volume.value = data.volume
  }

  function applyWeather(data: WeatherData): void {
    weather.value = { ...data, updated_at: new Date().toISOString() }
  }

  function applyReceipt(receipt: CommandReceipt): void {
    const item = pending.value[receipt.cmd_id]
    if (!item) return
    if (receipt.seq !== null) item.seq = receipt.seq

    switch (receipt.status) {
      case 'pending':
        status.value[item.action] = 'pending'
        break
      case 'accepted':
        // 只是受理，仍然黄，不能变绿
        status.value[item.action] = 'accepted'
        armTimeout(item)
        break
      case 'done':
        status.value[item.action] = 'ok'
        action.value = receipt.action
        dropPending(receipt.cmd_id)
        break
      case 'rejected':
        status.value[item.action] = 'fail'
        ElMessage.error(receipt.reason || '设备拒绝了这条动作')
        dropPending(receipt.cmd_id)
        break
      case 'unknown':
      case 'superseded':
      case 'legacy_unmapped':
        status.value[item.action] = 'unknown'
        dropPending(receipt.cmd_id)
        break
    }
  }

  function onAck(data: { cmd_id?: string; seq: number }): void {
    const item =
      (data.cmd_id ? pending.value[data.cmd_id] : undefined) ??
      Object.values(pending.value).find((entry) => entry.seq === data.seq)
    if (!item) return
    // ack 只表示"设备收到了"，不是执行完成
    status.value[item.action] = 'accepted'
    armTimeout(item)
  }

  function onEvent(event: WsEvent): void {
    lastPingAt = Date.now()
    switch (event.event) {
      case 'state':
        applyState(event.data)
        break
      case 'command':
        applyReceipt(event.data)
        break
      case 'ack':
        onAck(event.data)
        break
      case 'link':
        online.value = event.data.online
        controlState.value = event.data.control_state
        break
      case 'ping':
        break
      case 'music':
        applyMusic(event.data)
        break
      case 'weather':
        applyWeather(event.data)
        break
    }
  }

  function loadStoredPending(): void {
    const uidValue = uid()
    if (!uidValue || !currentDeviceId) return
    for (const refItem of getStoredPending(uidValue, currentDeviceId).slice(0, RECONCILE_MAX)) {
      if (pending.value[refItem.cmd_id]) continue
      const item: PendingCommand = {
        cmd_id: refItem.cmd_id,
        action: refItem.action,
        seq: null,
        timer: 0,
        expiry: 0,
        timedOut: true,
      }
      armTimeout(item)
      item.expiry = window.setTimeout(() => dropPending(refItem.cmd_id), PENDING_RETIRE_MS)
      pending.value[refItem.cmd_id] = item
      status.value[refItem.action] = 'unknown'
    }
  }

  function connect(deviceId: number): void {
    generation += 1
    const gen = generation
    openedOnce = false
    disconnectSocket()
    resetPending()
    resetState()
    currentDeviceId = deviceId

    if (!deviceId) {
      socketStatus.value = 'closed'
      return
    }

    loadStoredPending()

    socket = new DeviceSocket({
      deviceId,
      onEvent: (event) => {
        if (gen !== generation) return
        onEvent(event)
      },
      onStatus: (value) => {
        if (gen !== generation) return
        socketStatus.value = value
        if (value === 'closed') {
          // 断线时未拿到终态的命令一律显示"结果不明"，重连后再按 cmd_id 核对
          const affected = Object.values(pending.value).some(
            (item) => status.value[item.action] === 'pending' || status.value[item.action] === 'accepted',
          )
          for (const item of Object.values(pending.value)) {
            const current = status.value[item.action]
            if (current === 'pending' || current === 'accepted') {
              status.value[item.action] = 'unknown'
            }
          }
          if (affected) {
            ElMessage.warning('实时连接断开，未完成的动作结果不明；重连后会向后端核对')
          }
          return
        }
        if (value !== 'open') return
        if (!openedOnce) {
          openedOnce = true
          void loadSnapshot(deviceId, gen)
        }
        // 每次 open（含重连/刷新）都按 cmd_id 向后端核对，避免凭感觉判成功
        void reconcile(gen)
      },
      onClose: (code, message) => {
        if (gen !== generation) return
        void handleClose(code, message)
      },
    })
    void socket.connect()
  }

  async function handleClose(code: number, message?: string): Promise<void> {
    if (code === 1004) {
      // 身份失效：回登录页
      const [{ useAuthStore }, { default: router }] = await Promise.all([
        import('@/stores/auth'),
        import('@/router'),
      ])
      reset()
      useAuthStore().reset()
      ElMessage.warning('登录已失效，请重新登录')
      await router.replace('/login')
      return
    }
    if (code === 1008) {
      // 设备被解绑/归属丢失：只清设备，保留登录
      const [{ useDeviceStore }, { default: router }] = await Promise.all([
        import('@/stores/device'),
        import('@/router'),
      ])
      const deviceStore = useDeviceStore()
      const lostId = currentDeviceId
      reset()
      deviceStore.remove(lostId)
      ElMessage.warning('设备已被解绑')
      await router.replace('/devices')
      return
    }
    if (code === 4009) {
      ElMessage.error(message || '该设备已在其他窗口打开')
    }
  }

  function disconnectSocket(): void {
    socket?.close()
    socket = null
  }

  function disconnect(): void {
    generation += 1
    disconnectSocket()
    socketStatus.value = 'closed'
  }

  async function loadSnapshot(deviceId: number, gen: number): Promise<void> {
    try {
      const snapshot = await getDeviceStatus(deviceId)
      if (gen !== generation) return
      applyState({
        device_id: snapshot.device_id,
        online: snapshot.online,
        control_state: snapshot.control_state,
        session_id: snapshot.session_id,
        state_revision: snapshot.state_revision,
        battery: snapshot.battery,
        voltage: snapshot.voltage,
        action: snapshot.action,
        face: snapshot.face,
        music_state: snapshot.music_state,
        track: snapshot.track,
        volume: snapshot.volume,
        weather_code: snapshot.weather_code,
        temp: snapshot.temp,
      })
    } catch {
      // 统一错误提示已在 request 层弹过
    }
  }

  /** 断线重连/刷新后按 cmd_id 对账，后端记录才是唯一结论 */
  async function reconcile(gen: number): Promise<void> {
    if (gen !== generation) return
    const ids = Object.keys(pending.value).slice(0, RECONCILE_MAX)
    await Promise.all(
      ids.map(async (cmdId) => {
        try {
          const receipt = await getCommand(cmdId)
          if (gen !== generation) return
          if (!receipt) {
            dropPending(cmdId)
            return
          }
          applyReceipt(receipt)
        } catch {
          // 对账失败不打扰用户，下一次重连还会再来
        }
      }),
    )
  }

  /** 发一个动作：先黄"已提交"，收到 command done 才变绿 */
  async function sendAction(code: number): Promise<void> {
    const gen = generation
    const deviceId = currentDeviceId
    if (!deviceId) return

    const cmdId = newCmdId()
    addPending(cmdId, code)
    status.value[code] = 'pending'

    try {
      const receipt = await sendCommand(deviceId, code, cmdId)
      if (gen !== generation) return
      if (!pending.value[cmdId]) return
      applyReceipt(receipt)
    } catch (error) {
      if (gen !== generation) return
      if (error instanceof ApiError && error.code === -2) return
      const item = pending.value[cmdId]
      if (!item) return

      // 业务拒绝是明确失败；网络/500 是"不知道提交没提交"，只能显示结果不明
      if (
        error instanceof ApiError &&
        [40002, 40101, 40400, 40900].includes(error.code)
      ) {
        status.value[code] = 'fail'
        dropPending(cmdId)
        return
      }
      item.timedOut = true
      status.value[code] = 'unknown'
      ElMessage.warning('提交结果不明，重连后会向后端核对这条命令')
    }
  }

  async function changeFace(id: number): Promise<void> {
    const gen = generation
    if (!currentDeviceId) return
    try {
      await setCurrentFace(currentDeviceId, id)
      if (gen !== generation) return
      face.value = id
    } catch {
      // 统一提示由 request 层处理
    }
  }

  /** 天气本期关闭，保留给隐藏的 ClockCard 编译 */
  async function loadWeather(): Promise<void> {
    try {
      weather.value = await getWeather()
    } catch {
      // 天气失败不影响其它面板
    }
  }

  /** 音乐本期关闭，保留给隐藏的 MusicPanel 编译 */
  async function controlMusic(command: number, value = 0, deviceId = currentDeviceId): Promise<void> {
    if (!deviceId) return
    try {
      await sendMusic(deviceId, command, value)
    } catch {
      // 已统一提示
    }
  }

  function resetState(): void {
    online.value = false
    controlState.value = 'unconfigured'
    battery.value = null
    voltage.value = null
    action.value = null
    face.value = null
    weather.value = null
    musicState.value = 0
    track.value = 0
    volume.value = 15
    status.value = {}
    lastPingAt = 0
  }

  function resetPending(): void {
    Object.values(pending.value).forEach(clearTimers)
    pending.value = {}
  }

  function reset(): void {
    generation += 1
    resetPending()
    resetState()
    disconnectSocket()
    socketStatus.value = 'closed'
    online.value = false
    battery.value = 0
    voltage.value = 0

    action.value = 0
    face.value = 0
    musicState.value = 0
    track.value = 0
    volume.value = 15

    weather.value = null
    clearStoredPending(uid())
  }

  return {
    socketStatus,
    online,
    controlState,
    battery,
    voltage,
    action,
    face,
    weather,
    musicState,
    track,
    volume,
    status,
    pending,
    connected,
    musicLabel,
    lastPingAt,
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
