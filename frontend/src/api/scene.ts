import { request } from '@/utils/request'
import type { Scene, SceneStep } from '@/types'

export function listScenes(): Promise<Scene[]> {
  return request<Scene[]>({ url: '/scenes' })
}

export function createScene(payload: {
  name: string
  description?: string
  steps: SceneStep[]
}): Promise<Scene> {
  return request<Scene>({ url: '/scenes', method: 'post', data: payload })
}

export function updateScene(
  id: number,
  payload: { name?: string; description?: string; steps?: SceneStep[] },
): Promise<Scene> {
  return request<Scene>({ url: `/scenes/${id}`, method: 'put', data: payload })
}

export function deleteScene(id: number): Promise<unknown> {
  return request({ url: `/scenes/${id}`, method: 'delete' })
}

export function runScene(id: number): Promise<{ steps: number }> {
  return request<{ steps: number }>({ url: `/scenes/${id}/run`, method: 'post' })
}
