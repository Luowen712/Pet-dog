import { request } from '@/utils/request'
import type { FaceItem } from '@/types'

export function listFaces(): Promise<FaceItem[]> {
  return request<FaceItem[]>({ url: '/faces' })
}

export function setCurrentFace(
  deviceId: number,
  face: number,
): Promise<{ face: number; dispatched: true }> {
  return request({
    url: '/faces/current',
    method: 'post',
    data: { device_id: deviceId, face },
  })
}
