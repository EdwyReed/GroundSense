import type { WeatherDaySummary, WeatherMetricStatus } from './weatherDayTypes'

export type WeatherOutlookStatus = WeatherMetricStatus

export type WeatherOutlookData = {
  date: string
  timezone: 'UTC'
  basis: 'weather_model_not_field_observation'
  horizon_days: 2
  status: WeatherOutlookStatus
  days: WeatherDaySummary[]
}
