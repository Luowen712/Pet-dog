import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import type { ClaimableDevice, Device } from '@/types'
import {
  claimDevice as claimDeviceApi,
  listClaimableDevices,
  listDevices,
  renameDevice,
  unbindDevice as unbindDeviceApi,
} from '@/api/device'
import {
  clearStoredDeviceId,
  getStoredDeviceId,
  setStoredDeviceId,
} from '@/utils/session'

export const useDeviceStore = defineStore('device', () => {
  const devices = ref<Device[]>([])
  const claimable = ref<ClaimableDevice[]>([])
  const loading = ref(false)
  const loaded = ref(false)
  const currentId = ref(0)
  /** 当前绑定的是哪个账号；换账号必须先清空，不能沿用上一个人的设备 */
  let ownerUid: number | null = null

  const current = computed<Device | null>(
    () => devices.value.find((device) => device.id === currentId.value) ?? null,
  )
  const onlineCount = computed(() => devices.value.filter((device) => device.online).length)

  function bindUser(uid: number | null): void {
    if (ownerUid === uid) return
    ownerUid = uid
    devices.value = []
    claimable.value = []
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
    loading.value = true
    try {
      devices.value = await listDevices()
      loaded.value = true
      const exists = devices.value.some((device) => device.id === currentId.value)
      if (!exists) {
        if (devices.value.length > 0) {
          select(devices.value[0].id)
        } else {
          currentId.value = 0
          clearStoredDeviceId(ownerUid)
        }
      }
    } finally {
      loading.value = false
    }
  }

  async function loadClaimable(): Promise<void> {
    try {
      claimable.value = await listClaimableDevices()
    } catch {
      claimable.value = []
    }
  }

  async function claim(deviceId: number, code: string): Promise<Device> {
    const device = await claimDeviceApi(deviceId, code)
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
    await loadClaimable()
  }

  async function rename(id: number, name: string): Promise<void> {
    const updated = await renameDevice(id, name)
    devices.value = devices.value.map((device) =>
      device.id === id ? { ...device, ...updated } : device,
    )
  }

  function select(id: number): void {
    currentId.value = id
    if (ownerUid && id > 0) setStoredDeviceId(ownerUid, id)
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
    devices.value = []
    claimable.value = []
    loaded.value = false
    currentId.value = 0
  }

  return {
    devices,
    claimable,
    loading,
    loaded,
    currentId,
    current,
    onlineCount,
    bindUser,
    load,
    loadClaimable,
    claim,
    unbind,
    rename,
    select,
    remove,
    reset,
  }
})
