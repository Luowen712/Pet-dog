import { request } from '@/utils/request'
import type { Device, DeviceStatus } from '@/types'

export function listDevices(): Promise<Device[]> {
  return request<Device[]>({ url: '/devices' })
}

export function getDevice(id: number): Promise<Device> {
  return request<Device>({ url: `/devices/${id}` })
}

export function getDeviceStatus(id: number): Promise<DeviceStatus> {
  return request<DeviceStatus>({ url: `/devices/${id}/status` })
}
