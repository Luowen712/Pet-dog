export interface WeatherMeta {
  code: number
  text: string
  /** 屏幕图标画什么，前端按这个选 SVG */
  icon: 'sun' | 'partly' | 'cloud' | 'drizzle' | 'rain' | 'heavy-rain' | 'thunder' | 'snow' | 'fog' | 'unknown'
}

/** 10 个天气码，后端映射好，前端只管按码选图标 */
export const WEATHER_MAP: Record<number, WeatherMeta> = {
  0: { code: 0, text: '晴', icon: 'sun' },
  1: { code: 1, text: '多云', icon: 'partly' },
  2: { code: 2, text: '阴', icon: 'cloud' },
  3: { code: 3, text: '小雨', icon: 'drizzle' },
  4: { code: 4, text: '中雨', icon: 'rain' },
  5: { code: 5, text: '大雨', icon: 'heavy-rain' },
  6: { code: 6, text: '雷阵雨', icon: 'thunder' },
  7: { code: 7, text: '雪', icon: 'snow' },
  8: { code: 8, text: '雾', icon: 'fog' },
  9: { code: 9, text: '未知', icon: 'unknown' },
}

/** 天气展示地点：湖南省湘潭市雨湖区（区政府附近） */
export const WEATHER_LOCATION = {
  name: '湘潭 · 雨湖区',
  latitude: 27.856,
  longitude: 112.903,
  timezone: 'Asia/Shanghai',
}

/**
 * Open-Meteo 返回的是 WMO 天气码，不是项目的 0–9。
 * 映射口径与《项目分工与实施方案 V2.0》6.5 一致。
 */
export function weatherCodeFromWmo(wmo: number): number {
  if (wmo === 0 || wmo === 1) return 0
  if (wmo === 2) return 1
  if (wmo === 3) return 2
  if ([51, 53, 55, 61].includes(wmo)) return 3
  if ([63, 80, 81].includes(wmo)) return 4
  if ([65, 82].includes(wmo)) return 5
  if ([95, 96, 99].includes(wmo)) return 6
  if ([71, 73, 75].includes(wmo)) return 7
  if ([45, 48].includes(wmo)) return 8
  return 9
}

export function weatherMeta(code?: number): WeatherMeta {
  return WEATHER_MAP[code ?? 9] ?? WEATHER_MAP[9]
}
