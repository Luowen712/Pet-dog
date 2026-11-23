import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import type { BleDevice, Device } from '@/types'
import {
  connectBleDevice as connectBleDeviceApi,
  listDevices,
  renameDevice,
  scanBleDevices,
  unbindDevice as unbindDeviceApi,
} from '@/api/device'
import {
  clearStoredDeviceId,
  getStoredDeviceId,
  setStoredDeviceId,
} from '@/utils/session'

export const useDeviceStore = defineStore('device', () => {
  const devices = ref<Device[]>([])
  const bleDevices = ref<BleDevice[]>([])
  const scanning = ref(false)
  const loading = ref(false)
  const loaded = ref(false)
  const currentId = ref(0)
  /** 当前绑定的是哪个账号；换账号必须先清空，不能沿用上一个人的设备 */
  let ownerUid: number | null = null
  let inflightLoad: Promise<void> | null = null
  let scanGen = 0

  const current = computed<Device | null>(
    () => devices.value.find((device) => device.id === currentId.value) ?? null,
  )
  const onlineCount = computed(() => devices.value.filter((device) => device.online).length)

  function bindUser(uid: number | null): void {
    if (ownerUid === uid) return
    ownerUid = uid
    inflightLoad = null
    scanGen += 1
    loading.value = false
    scanning.value = false
    devices.value = []
    bleDevices.value = []
    loaded.value = false
    currentId.value = uid ? getStoredDeviceId(uid) ?? 0 : 0
  }

  async function load(): Promise<void> {
    if (!ownerUid) {
      devices.value = []
      loaded.value = true
      currentId.value = 0
      return
    }
    if (inflightLoad) return inflightLoad
    const expectedUid = ownerUid
    const run = async (): Promise<void> => {
      loading.value = true
      try {
        const list = await listDevices()
        if (ownerUid !== expectedUid) return
        devices.value = list
        loaded.value = true
        const exists = devices.value.some((device) => device.id === currentId.value)
        if (!exists) {
          if (devices.value.length > 0) {
            select(devices.value[0].id)
          } else {
            currentId.value = 0
            clearStoredDeviceId(expectedUid)
          }
        }
      } finally {
        if (ownerUid === expectedUid) loading.value = false
        if (inflightLoad === job) inflightLoad = null
      }
    }
    const job = run()
    inflightLoad = job
    return job
  }

  async function scanBle(): Promise<void> {
    if (scanning.value || !ownerUid) return
    const expectedUid = ownerUid
    const myGen = ++scanGen
    scanning.value = true
    try {
      const found = await scanBleDevices()
      if (myGen !== scanGen || ownerUid !== expectedUid) return
      bleDevices.value = found
    } catch {
      if (myGen === scanGen && ownerUid === expectedUid) bleDevices.value = []
    } finally {
      if (myGen === scanGen) scanning.value = false
    }
  }

  async function connectBle(address: string, name?: string): Promise<Device> {
    const device = await connectBleDeviceApi(address, name)
    await load()
    select(device.id)
    return device
  }

  async function unbind(id: number): Promise<void> {
    await unbindDeviceApi(id, id)
    if (currentId.value === id) {
      currentId.value = 0
      clearStoredDeviceId(ownerUid)
    }
    await load()
    await scanBle()
  }

  async function rename(id: number, name: string): Promise<void> {
    const updated = await renameDevice(id, name)
    devices.value = devices.value.map((device) =>
      device.id === id ? { ...device, ...updated } : device,
    )
  }

  function select(id: number): void {
    if (id > 0 && loaded.value && !devices.value.some((device) => device.id === id)) return
    currentId.value = id
    if (ownerUid && id > 0) setStoredDeviceId(ownerUid, id)
  }

  /** 用 WS 实时事件刷新设备卡片的在线/控制/电量/心跳字段，避免页面停留时显示过期离线态 */
  function patchLive(
    id: number,
    patch: Partial<Pick<Device, 'online' | 'control_state' | 'battery' | 'last_heartbeat'>>,
  ): void {
    if (!id) return
    const idx = devices.value.findIndex((device) => device.id === id)
    if (idx < 0) return
    devices.value[idx] = { ...devices.value[idx], ...patch }
  }

  /** 设备被解绑 / 归属丢失：只清设备，保留登录态 */
  function remove(id: number): void {
    devices.value = devices.value.filter((device) => device.id !== id)
    if (currentId.value === id) {
      currentId.value = 0
      clearStoredDeviceId(ownerUid)
      if (devices.value.length > 0) select(devices.value[0].id)
    }
  }

  function reset(): void {
    ownerUid = null
    inflightLoad = null
    scanGen += 1
    devices.value = []
    bleDevices.value = []
    loading.value = false
    scanning.value = false
    loaded.value = false
    currentId.value = 0
  }

  return {
    devices,
    bleDevices,
    scanning,
    loading,
    loaded,
    currentId,
    current,
    onlineCount,
    bindUser,
    load,
    scanBle,
    connectBle,
    unbind,
    rename,
    select,
    patchLive,
    remove,
    reset,
  }
})
