import { request } from '@/utils/request'
import type { BleDevice, Device, DeviceStatus } from '@/types'

export function listDevices(): Promise<Device[]> {
  return request<Device[]>({ url: '/devices' })
}

export function getDevice(id: number): Promise<Device> {
  return request<Device>({ url: `/devices/${id}` })
}

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

export function scanBleDevices(): Promise<BleDevice[]> {
  return request<BleDevice[]>({ url: '/devices/ble/scan', timeout: 15000 })
}

export function connectBleDevice(address: string, name?: string): Promise<Device> {
  return request<Device>({
    url: '/devices/ble/connect',
    method: 'post',
    data: { address, ...(name ? { name } : {}) },
    timeout: 20000,
  })
}

export function unbindDevice(
  id: number,
  confirmDeviceId: number,
): Promise<{ unbound: true; handover_required: true }> {
  return request({
    url: `/devices/${id}/binding`,
    method: 'delete',
    data: { confirm_device_id: confirmDeviceId },
  })
}
