export type EyeStyle = 'line' | 'round' | 'star' | 'slant' | 'chevron' | 'capsule' | 'big'
export type MouthStyle = 'o' | 'frown' | 'cat' | 'smile' | 'omega' | 'none'

export interface FaceDef {
  id: number
  name: string
  eyes: EyeStyle
  mouth: MouthStyle
  blush?: boolean
}

/**
 * 7 张内置表情，编号 0~6 与嵌入式固件 DebugUI.c / OLED_Data.c 严格对齐：
 *   0 睡觉 (Face_sleep) · 1 委屈 (Face_stare) · 2 开心 (Face_happy) · 3 狂热 (Face_mania)
 *   4 超开心 (Face_very_happy) · 5 眼睛 (Face_eyes，上电默认) · 6 震惊 (Face_hello)
 */
export const FACES: FaceDef[] = [
  { id: 0, name: '睡觉', eyes: 'line', mouth: 'o' },
  { id: 1, name: '委屈', eyes: 'round', mouth: 'frown' },
  { id: 2, name: '开心', eyes: 'star', mouth: 'cat', blush: true },
  { id: 3, name: '狂热', eyes: 'slant', mouth: 'smile', blush: true },
  { id: 4, name: '超开心', eyes: 'chevron', mouth: 'omega', blush: true },
  { id: 5, name: '眼睛', eyes: 'capsule', mouth: 'none' },
  { id: 6, name: '震惊', eyes: 'big', mouth: 'o' },
]

export const FACE_BY_ID = new Map<number, FaceDef>(FACES.map((face) => [face.id, face]))

export function faceName(id?: number): string {
  return FACE_BY_ID.get(id ?? -1)?.name ?? '未知'
}
