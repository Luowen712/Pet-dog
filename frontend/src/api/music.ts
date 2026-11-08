import { request } from '@/utils/request'

/** 音乐子命令：0 停止 1 播放 2 暂停 3 下一首 4 上一首 5 音量 */
export const MUSIC_STOP = 0
export const MUSIC_PLAY = 1
export const MUSIC_PAUSE = 2
export const MUSIC_NEXT = 3
export const MUSIC_PREV = 4
export const MUSIC_VOLUME = 5

export function sendMusic(deviceId: number, command: number, value = 0): Promise<unknown> {
  return request({
    url: `/devices/${deviceId}/music`,
    method: 'post',
    data: { command, value },
  })
}
