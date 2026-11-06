import { request } from '@/utils/request'
import type { WeatherInfo } from '@/types'

export function getWeather(): Promise<WeatherInfo> {
  return request<WeatherInfo>({ url: '/weather' })
}
