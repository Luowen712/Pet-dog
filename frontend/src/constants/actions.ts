export type ActionGroup = '姿态' | '移动' | '转向' | '互动' | '灯光'

export interface ActionDef {
  code: number
  name: string
  group: ActionGroup
  hint: string
}

export const ACTION_GROUPS: ActionGroup[] = ['姿态', '移动', '转向', '互动', '灯光']

/**
 * 19 个动作码，与《前端线开发计划 V2.0》7.5 节一致。
 * 0x46 / 0x47 是呼吸灯，计划里明确只做 19 个按钮，这里不铺。
 */
export const ACTIONS: ActionDef[] = [
  { code: 0x29, name: '放松趴下', group: '姿态', hint: '四肢放松，肚皮贴地' },
  { code: 0x30, name: '蹲下', group: '姿态', hint: '后腿压低，前腿撑住' },
  { code: 0x31, name: '站立', group: '姿态', hint: '五个舵机回到 90° 中位' },
  { code: 0x32, name: '趴下', group: '姿态', hint: '四条腿同时收起' },
  { code: 0x33, name: '前进', group: '移动', hint: '四腿交替前移约 10 cm' },
  { code: 0x34, name: '后退', group: '移动', hint: '反序后移约 10 cm' },
  { code: 0x38, name: '提速', group: '移动', hint: '步频提升一档' },
  { code: 0x41, name: '前跳', group: '移动', hint: '四腿同时蹬起再落回' },
  { code: 0x42, name: '后跳', group: '移动', hint: '向后蹬跳一步' },
  { code: 0x48, name: '伸懒腰', group: '移动', hint: '前伸后蹬，保持两秒' },
  { code: 0x49, name: '后腿拉伸', group: '移动', hint: '两条后腿轮流伸展' },
  { code: 0x35, name: '左转', group: '转向', hint: '机身左转约 45°' },
  { code: 0x36, name: '右转', group: '转向', hint: '机身右转约 45°' },
  { code: 0x37, name: '摇摆', group: '转向', hint: '左右交替摆身' },
  { code: 0x39, name: '摇摆加速', group: '转向', hint: '摇摆步频加快' },
  { code: 0x40, name: '摇尾巴', group: '转向', hint: '尾巴左右摆三下' },
  { code: 0x43, name: '打招呼', group: '互动', hint: '抬前腿 + 笑脸' },
  { code: 0x44, name: '开灯', group: '灯光', hint: '点亮头部 LED' },
  { code: 0x45, name: '关灯', group: '灯光', hint: '熄灭头部 LED' },
]

export const ACTION_BY_CODE = new Map<number, ActionDef>(ACTIONS.map((item) => [item.code, item]))

export function actionName(code: number): string {
  return ACTION_BY_CODE.get(code)?.name ?? `未知动作 ${actionHex(code)}`
}

export function actionHex(code: number): string {
  return `0x${code.toString(16).toUpperCase().padStart(2, '0')}`
}

export function actionsOf(group: ActionGroup): ActionDef[] {
  return ACTIONS.filter((item) => item.group === group)
}
