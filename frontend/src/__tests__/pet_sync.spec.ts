import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import type { CommandReceipt, DeviceStatus, WsEvent } from '@/types'

type MockSocketRecord = {
  options: {
    deviceId: number
    onEvent: (event: WsEvent) => void
    onStatus: (status: 'connecting' | 'open' | 'closed') => void
    onClose: (code: number, message?: string) => void
  }
  resync: ReturnType<typeof vi.fn>
  close: ReturnType<typeof vi.fn>
}

const sockets: MockSocketRecord[] = []
const getDeviceStatusMock = vi.fn<() => Promise<DeviceStatus>>()
const getCommandMock = vi.fn<(id: string) => Promise<CommandReceipt | null>>()
const sendCommandMock = vi.fn()
const handleUnauthorizedMock = vi.fn()
const routerReplaceMock = vi.fn<(to: unknown) => Promise<void>>(async () => {})

vi.mock('@/router', () => ({
  default: { replace: (to: unknown) => routerReplaceMock(to) },
}))

vi.mock('@/api/device', () => ({
  getDeviceStatus: (...args: unknown[]) => getDeviceStatusMock(...(args as [])),
  listDevices: vi.fn(async () => []),
  scanBleDevices: vi.fn(async () => []),
  connectBleDevice: vi.fn(),
  renameDevice: vi.fn(),
  unbindDevice: vi.fn(),
}))

vi.mock('@/api/command', () => ({
  getCommand: (id: string) => getCommandMock(id),
  sendCommand: (...args: unknown[]) => sendCommandMock(...args),
}))

vi.mock('@/utils/request', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/utils/request')>()
  return { ...actual, handleUnauthorized: (...args: unknown[]) => handleUnauthorizedMock(...args) }
})

vi.mock('@/utils/ws', () => ({
  DeviceSocket: class {
    options: MockSocketRecord['options']
    resync = vi.fn()
    close = vi.fn()
    constructor(options: MockSocketRecord['options']) {
      this.options = options
      sockets.push({ options, resync: this.resync, close: this.close })
    }
    async connect(): Promise<void> {}
  },
}))

function baseStatus(overrides: Partial<DeviceStatus> = {}): DeviceStatus {
  return {
    device_id: 1,
    online: true,
    control_state: 'ready',
    session_id: 'sid-1',
    state_revision: 5,
    battery: 80,
    voltage: 7.4,
    action: 0,
    face: 0,
    music_state: null,
    track: null,
    volume: null,
    weather_code: null,
    temp: null,
    updated_at: '2026-11-22T00:00:00Z',
    ...overrides,
  }
}

function receiptOf(overrides: Partial<CommandReceipt> = {}): CommandReceipt {
  return {
    cmd_id: 'cmd-1',
    device_id: 1,
    action: 49,
    seq: 1,
    status: 'pending',
    transport: 'ok',
    reason: null,
    error_code: null,
    revision: 1,
    created_at: '2026-11-22T00:00:00Z',
    updated_at: '2026-11-22T00:00:00Z',
    finished_at: null,
    ...overrides,
  }
}

describe('pet store 重连对账、unknown 保留与关闭码', () => {
  beforeEach(() => {
    localStorage.clear()
    localStorage.setItem('petdog_token', 'tok')
    localStorage.setItem('petdog_user', JSON.stringify({ id: 7, username: 'u', name: 'u', role: 'user' }))
    sockets.length = 0
    vi.clearAllMocks()
    setActivePinia(createPinia())
  })

  it('每次重连都重新拉快照，并按 session_id/state_revision 重放缓冲事件', async () => {
    const { usePetStore } = await import('@/stores/pet')
    const pet = usePetStore()
    let resolveSnap!: (v: DeviceStatus) => void
    getDeviceStatusMock.mockImplementationOnce(() => new Promise((r) => { resolveSnap = r }))
    getCommandMock.mockResolvedValue(null)

    pet.connect(1)
    const sock = sockets[0]
    sock.options.onStatus('open')
    // 快照返回前收到旧版本与新版本缓冲事件
    sock.options.onEvent({ event: 'state', data: baseStatus({ state_revision: 4, battery: 11 }) })
    sock.options.onEvent({ event: 'state', data: baseStatus({ state_revision: 6, battery: 92 }) })
    resolveSnap(baseStatus({ state_revision: 5, battery: 80 }))
    await vi.waitFor(() => expect(pet.battery).toBe(92))
    expect(getDeviceStatusMock).toHaveBeenCalledTimes(1)

    // 断线再重连必须重新拉快照
    getDeviceStatusMock.mockResolvedValueOnce(baseStatus({ session_id: 'sid-2', state_revision: 1, battery: 66 }))
    sock.options.onStatus('closed')
    sock.options.onStatus('open')
    await vi.waitFor(() => expect(pet.battery).toBe(66))
    expect(getDeviceStatusMock).toHaveBeenCalledTimes(2)
  })

  it('可能已写出的 unknown 保留 pending 等迟到 done，write_failed 直接移除', async () => {
    const { usePetStore } = await import('@/stores/pet')
    const pet = usePetStore()
    getDeviceStatusMock.mockResolvedValue(baseStatus())
    getCommandMock.mockResolvedValue(null)

    pet.connect(1)
    const sock = sockets[0]
    sock.options.onStatus('open')
    await vi.waitFor(() => expect(pet.controlState).toBe('ready'))

    sendCommandMock.mockImplementationOnce(async (_dev: number, action: number, cmdId: string) =>
      receiptOf({ cmd_id: cmdId, action, status: 'unknown', transport: 'ok', revision: 2 }),
    )
    await pet.sendAction(49)
    const [keptId] = Object.keys(pet.pending)
    expect(keptId).toBeTruthy()
    expect(pet.status[49]).toBe('unknown')

    // 迟到 done 到达后把按钮纠正为 ok 并清掉 pending
    sock.options.onEvent({
      event: 'command',
      data: receiptOf({ cmd_id: keptId, action: 49, status: 'done', transport: 'ok', revision: 3 }),
    })
    expect(pet.status[49]).toBe('ok')
    expect(pet.pending[keptId]).toBeUndefined()

    // 确定未写 write_failed 不应留在 pending
    sendCommandMock.mockImplementationOnce(async (_dev: number, action: number, cmdId: string) =>
      receiptOf({ cmd_id: cmdId, action, status: 'unknown', transport: 'write_failed', revision: 2 }),
    )
    await pet.sendAction(50)
    expect(Object.keys(pet.pending)).toHaveLength(0)
  })

  it('关闭码 4401 走统一登出，1008 只清设备保留登录态', async () => {
    const { usePetStore } = await import('@/stores/pet')
    const { useDeviceStore } = await import('@/stores/device')
    const pet = usePetStore()
    const deviceStore = useDeviceStore()
    deviceStore.bindUser(7)
    deviceStore.devices = [{
      id: 1, name: 'Pet', online: true, firmware: '2.0', last_heartbeat: null, battery: 80,
      binding_state: 'bound', control_state: 'ready', supported_actions: [49],
    }]
    deviceStore.select(1)

    pet.connect(1)
    sockets[0].options.onClose(4401)
    await vi.waitFor(() => expect(handleUnauthorizedMock).toHaveBeenCalledTimes(1))

    pet.connect(1)
    sockets[1].options.onClose(1008)
    await vi.waitFor(() => expect(routerReplaceMock).toHaveBeenCalledWith('/devices'))
    expect(deviceStore.devices).toHaveLength(0)
    expect(localStorage.getItem('petdog_token')).toBe('tok')
  })
})
