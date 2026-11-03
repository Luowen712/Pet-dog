import { request } from '@/utils/request'
import type { FaceItem } from '@/types'

export function listFaces(): Promise<FaceItem[]> {
  return request<FaceItem[]>({ url: '/faces' })
}

/** 接口路径文档未定死，这里按 /faces/current 约定，联调时以后端 /docs 为准 */
export function setCurrentFace(face: number): Promise<{ face: number }> {
  return request<{ face: number }>({
    url: '/faces/current',
    method: 'post',
    data: { face },
  })
}

export function uploadFace(file: File): Promise<FaceItem> {
  const form = new FormData()
  form.append('file', file)
  return request<FaceItem>({ url: '/faces', method: 'post', data: form })
}

export function deleteFace(id: number): Promise<unknown> {
  return request({ url: `/faces/${id}`, method: 'delete' })
}
