import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import type { Device } from '@/types'
import { listDevices, renameDevice } from '@/api/device'
import { getStoredDeviceId, setStoredDeviceId } from '@/utils/session'

export const useDeviceStore = defineStore('device', () => {
  const devices = ref<Device[]>([])
  const loading = ref(false)
  const loaded = ref(false)
  const currentId = ref(getStoredDeviceId())

  const current = computed<Device | null>(
    () => devices.value.find((device) => device.id === currentId.value) ?? null,
  )
  const onlineCount = computed(() => devices.value.filter((device) => device.online).length)

  async function load(): Promise<void> {
    loading.value = true
    try {
      devices.value = await listDevices()
      loaded.value = true
      const exists = devices.value.some((device) => device.id === currentId.value)
      if (!exists && devices.value.length > 0) select(devices.value[0].id)
    } finally {
      loading.value = false
    }
  }

  async function rename(id: number, name: string): Promise<void> {
    const updated = await renameDevice(id, name)
    devices.value = devices.value.map((device) =>
      device.id === id ? { ...device, ...updated } : device,
    )
  }

  function select(id: number): void {
    currentId.value = id
    setStoredDeviceId(id)
  }

  return { devices, loading, loaded, currentId, current, onlineCount, load, rename, select }
})
