export type AntecedentPrecipitationStatus = 'available' | 'partial' | 'unavailable'

export type AntecedentPrecipitationDay = {
  date: string
  status: AntecedentPrecipitationStatus
  total_mm: number | null
  known_intervals: number
  expected_intervals: 24
}

export type AntecedentPrecipitationSummary = {
  date: string | null
  timezone: 'UTC'
  basis: 'weather_model_not_field_observation'
  window_start: string | null
  window_end_exclusive: string | null
  window_days: 7
  status: AntecedentPrecipitationStatus
  total_mm: number | null
  known_intervals: number
  expected_intervals: 168
  days: AntecedentPrecipitationDay[]
}
