import { request } from '@/utils/request'
import type { ClaimableDevice, Device, DeviceStatus } from '@/types'

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

export function listClaimableDevices(): Promise<ClaimableDevice[]> {
  return request<ClaimableDevice[]>({ url: '/devices/claimable' })
}

export function claimDevice(deviceId: number, code: string): Promise<Device> {
  return request<Device>({
    url: '/devices/claim',
    method: 'post',
    data: { device_id: deviceId, code },
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
