export type EyeStyle = 'round' | 'arc' | 'line' | 'slant' | 'big' | 'star'
export type MouthStyle = 'smile' | 'frown' | 'o' | 'flat' | 'cat'

export interface FaceDef {
  id: number
  name: string
  eyes: EyeStyle
  mouth: MouthStyle
  blush?: boolean
}

/** 屏幕上半 128×32 的 7 张内置表情，按编号 0~6 下发 */
export const FACES: FaceDef[] = [
  { id: 0, name: '普通', eyes: 'round', mouth: 'flat' },
  { id: 1, name: '开心', eyes: 'arc', mouth: 'smile' },
  { id: 2, name: '困倦', eyes: 'line', mouth: 'o' },
  { id: 3, name: '生气', eyes: 'slant', mouth: 'frown' },
  { id: 4, name: '惊讶', eyes: 'big', mouth: 'o' },
  { id: 5, name: '伤心', eyes: 'round', mouth: 'frown' },
  { id: 6, name: '卖萌', eyes: 'star', mouth: 'cat', blush: true },
]

export const FACE_BY_ID = new Map<number, FaceDef>(FACES.map((face) => [face.id, face]))

export function faceName(id?: number): string {
  return FACE_BY_ID.get(id ?? -1)?.name ?? '未知'
}
