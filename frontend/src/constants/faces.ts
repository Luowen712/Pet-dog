export type EyeStyle =
  | 'round'
  | 'arc'
  | 'line'
  | 'slant'
  | 'big'
  | 'star'
  | 'square'
  | 'capsule'
  | 'chevron'
export type MouthStyle = 'smile' | 'frown' | 'o' | 'flat' | 'cat' | 'omega' | 'none'

export interface FaceDef {
  id: number
  name: string
  eyes: EyeStyle
  mouth: MouthStyle
  blush?: boolean
}

/**
 * 屏幕上半 128×32 的 7 张内置表情，按编号 0~6 下发。
 *
 * 0 / 1 / 2 / 3 的造型对齐实体硬件的 OLED 显示：
 *   00 两块方眼（无嘴）  · 01 `>ω<`  · 02 两枚竖圆眼（无嘴）  · 03 `>ω<`
 * 硬件屏底部那行 A:00 S:00 B:1 F:0 L1 E:000 N:0000 是调试编码，
 * 属于屏上叠加的遥测文字，不是表情的一部分，这里一律不画。
 */
export const FACES: FaceDef[] = [
  { id: 0, name: '普通', eyes: 'square', mouth: 'none' },
  { id: 1, name: '开心', eyes: 'chevron', mouth: 'omega' },
  { id: 2, name: '困倦', eyes: 'capsule', mouth: 'none' },
  { id: 3, name: '生气', eyes: 'chevron', mouth: 'omega' },
  { id: 4, name: '惊讶', eyes: 'big', mouth: 'o' },
  { id: 5, name: '伤心', eyes: 'round', mouth: 'frown' },
  { id: 6, name: '卖萌', eyes: 'star', mouth: 'cat', blush: true },
]

export const FACE_BY_ID = new Map<number, FaceDef>(FACES.map((face) => [face.id, face]))

export function faceName(id?: number): string {
  return FACE_BY_ID.get(id ?? -1)?.name ?? '未知'
}
