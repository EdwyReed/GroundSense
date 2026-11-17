export type WeatherMetricStatus = 'available' | 'partial' | 'unavailable'
export type WeatherDaySummary = {
  date: string
  timezone: 'UTC'
  status: WeatherMetricStatus
  basis: 'weather_model_not_field_observation'
  precipitation: { status: WeatherMetricStatus; total_mm: number | null; known_intervals: number; expected_intervals: 24 }
  soil_temperature: { status: WeatherMetricStatus; min_c: number | null; max_c: number | null; known_samples: number; expected_samples: 24; at_or_below_zero_samples: number }
  snow_depth: { status: WeatherMetricStatus; min_m: number | null; max_m: number | null; known_samples: number; expected_samples: 24 }
}
