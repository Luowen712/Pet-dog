import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { ElMessage } from 'element-plus'
import type {
  AckData,
  CommandReceipt,
  StateData,
  WeatherInfo,
  WsEvent,
} from '@/types'
import { getDeviceStatus } from '@/api/device'
import { getCommand, sendCommand } from '@/api/command'
import { sendMusic } from '@/api/music'
import { setCurrentFace } from '@/api/face'
import { getWeather } from '@/api/weather'
import { DeviceSocket } from '@/utils/ws'
import type { SocketStatus } from '@/utils/ws'

export type ButtonState = 'idle' | 'pending' | 'ok' | 'fail'

/**
 * 按钮「变红」只是展示层的乐观反馈，不是命令结论：
 * 契约里命令的终态只由后端 command_log 判定（T_ACK_MS = 600ms 后置 unknown 等）。
 * 两个数值不要互相引用，见 docs/contracts/http-api.md §1.7。
 */
const DISPLAY_TIMEOUT_MS = 3000

/** seq 映射表的保留窗口（契约 SEQ_RETIRE_MS）：过窗口后 ack 只能靠 cmd_id 认领 */
const SEQ_RETIRE_MS = 30000

/** 一次对账最多查 20 条，契约明确要求不要无限查 */
const RECONCILE_MAX = 20

const TERMINAL: ReadonlySet<string> = new Set(['done', 'rejected', 'unknown', 'superseded'])

interface PendingCommand {
  cmd_id: string
  seq: number
  action: number
  /** 按钮变红的展示计时器 */
  timer: number
  /** 到期清理 pending 映射，避免无限增长 */
  expiry: number
  timedOut: boolean
}

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
  /** cmd_id → 命令。主键是后端给的 cmd_id，seq 只用来认领没有 cmd_id 的 ack */
  const pending = ref<Record<string, PendingCommand>>({})

  let socket: DeviceSocket | null = null
  /** 连接代次：切设备/重连都会 +1，异步回来的旧结果一律丢弃 */
  let generation = 0
  let currentDeviceId = 0
  /** 最近一条 WS 事件的时刻，用来判断 HTTP 快照是不是已经过期 */
  let lastEventAt = 0
  /** 本次连接是否已经 open 过一次（首次 open 由 connect 里的 loadSnapshot 负责） */
  let openedOnce = false

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

  function clearTimers(item: PendingCommand): void {
    window.clearTimeout(item.timer)
    window.clearTimeout(item.expiry)
  }

  function dropPending(cmdId: string): void {
    const item = pending.value[cmdId]
    if (!item) return
    clearTimers(item)
    delete pending.value[cmdId]
  }

  function applyReceipt(receipt: CommandReceipt): void {
    const item = pending.value[receipt.cmd_id]
    if (!item) return
    if (!TERMINAL.has(receipt.status)) return // pending / accepted：还在跑，继续等
    dropPending(receipt.cmd_id)
    status.value[item.action] = receipt.status === 'done' ? 'ok' : 'fail'
  }

  function onAck(data: AckData): void {
    const item =
      (data.cmd_id ? pending.value[data.cmd_id] : undefined) ??
      Object.values(pending.value).find((entry) => entry.seq === data.seq)
    if (!item) return // 迟到的 ack：映射已过保留窗口，终态以后端记录为准
    dropPending(item.cmd_id)
    status.value[item.action] = data.status === 'OK' ? 'ok' : 'fail'
    if (data.status !== 'OK') ElMessage.error('设备执行失败，请重试')
  }

  function onEvent(event: WsEvent): void {
    lastEventAt = Date.now()
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
    generation += 1
    const gen = generation
    openedOnce = false
    disconnectSocket()
    resetPending()
    currentDeviceId = deviceId

    socket = new DeviceSocket({
      deviceId,
      onEvent,
      onStatus: (value) => {
        if (gen !== generation) return // 旧连接的关闭回调不许覆盖新连接的状态
        socketStatus.value = value
        if (value !== 'open') return
        if (!openedOnce) {
          openedOnce = true
          return
        }
        // 断线重连：契约 §7 五步里的第 3、4 步
        void reconcile(gen)
      },
      onFatal: (message) => ElMessage.error(message),
    })
    void socket.connect()
    void loadSnapshot(deviceId, gen)
    void loadWeather()
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

  async function loadSnapshot(deviceId: number, gen = generation): Promise<void> {
    const startedAt = Date.now()
    try {
      const snapshot = await getDeviceStatus(deviceId)
      // 竞态：切了设备 / 更新的 WS 事件已经先行到达，旧快照直接丢
      if (gen !== generation || lastEventAt > startedAt) return
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

  /** 重连对账：先把 11 个状态字段拉回来，再逐条核对还在等回执的命令 */
  async function reconcile(gen: number): Promise<void> {
    if (gen !== generation) return
    await loadSnapshot(currentDeviceId, gen)
    if (gen !== generation) return

    const cmdIds = Object.keys(pending.value).slice(0, RECONCILE_MAX)
    await Promise.all(
      cmdIds.map(async (cmdId) => {
        try {
          const receipt = await getCommand(cmdId)
          if (gen !== generation) return
          if (!receipt) {
            // 记录已被清理：保留按钮现状，只把映射收掉，不臆造终态
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

  /** 发一个动作：立刻变黄，收到 ack 变绿；3 秒没回执只把按钮标红，命令结论以后端为准 */
  async function sendAction(code: number): Promise<void> {
    status.value[code] = 'pending'
    try {
      const res = await sendCommand(code)
      const item: PendingCommand = {
        cmd_id: res.cmd_id,
        seq: res.seq,
        action: code,
        timer: 0,
        expiry: 0,
        timedOut: false,
      }
      item.timer = window.setTimeout(() => {
        const live = pending.value[item.cmd_id]
        if (!live || live.timedOut) return
        live.timedOut = true
        status.value[code] = 'fail'
        // 契约 error-codes.md §4：TIMEOUT 的文案不能写「失败」，它可能是成功但回执丢了
        ElMessage.warning('3 秒内没收到回执，结果不明，请以后端命令日志为准')
      }, DISPLAY_TIMEOUT_MS)
      item.expiry = window.setTimeout(() => dropPending(item.cmd_id), SEQ_RETIRE_MS)
      pending.value[item.cmd_id] = item
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

  function resetPending(): void {
    Object.values(pending.value).forEach(clearTimers)
    pending.value = {}
  }

  function reset(): void {
    generation += 1
    resetPending()
    status.value = {}
    disconnectSocket()
    socketStatus.value = 'closed'
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
