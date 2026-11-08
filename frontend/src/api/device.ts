import { request } from '@/utils/request'
import type { Device, DeviceStatus } from '@/types'

export function listDevices(): Promise<Device[]> {
  return request<Device[]>({ url: '/devices' })
}

export function getDevice(id: number): Promise<Device> {
  return request<Device>({ url: `/devices/${id}` })
}

/** 改桌宠名字：契约里还没定义，暂按 PATCH /devices/{id} { name } 写 */
export function renameDevice(id: number, name: string): Promise<Device> {
  return request<Device>({
    url: `/devices/${id}`,
    method: 'patch',
    data: { name },
  })
}

export function getDeviceStatus(id: number): Promise<DeviceStatus> {
  return request<DeviceStatus>({ url: `/devices/${id}/status` })
}
