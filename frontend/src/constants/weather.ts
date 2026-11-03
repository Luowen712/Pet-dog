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

export function weatherMeta(code?: number): WeatherMeta {
  return WEATHER_MAP[code ?? 9] ?? WEATHER_MAP[9]
}
