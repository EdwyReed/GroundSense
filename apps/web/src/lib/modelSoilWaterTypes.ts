import type { LngLat } from './routeTypes'

export type ModelSoilWaterStatus = 'available' | 'partial' | 'unavailable'
export type ModelSoilWaterLayer = {
  variable: string
  from_cm: number
  to_cm: number
  status: ModelSoilWaterStatus
  min_m3_m3: number | null
  max_m3_m3: number | null
  known_samples: number
  expected_samples: number
}
export type ModelSoilWaterData = {
  date: string | null
  timezone: string
  basis: string
  status: ModelSoilWaterStatus
  source_id: string | null
  model: string | null
  source_sha256: string | null
  unit: string
  requested_point: LngLat | null
  grid_point: LngLat | null
  layers: ModelSoilWaterLayer[]
}
