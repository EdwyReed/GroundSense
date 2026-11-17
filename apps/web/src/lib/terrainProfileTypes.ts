import type { ContextSource } from './sectionContextTypes'
import type { LngLat } from './routeTypes'
import type { LandCoverTrace } from './landCoverTraceTypes'
import type { SurfaceProfileSummary } from './surfaceProfileTypes'

export type TerrainProfilePoint = {
  chainage_m: number
  point: LngLat
  elevation_m: number | null
  land_cover_class: number | null
  land_cover_label: string | null
}

export type TerrainProfileResponse = {
  plan_id: string
  route_id: string
  trip_date: string
  status: string
  synthetic: false
  evidence_scope: 'spaced_point_samples'
  coverage: 'not_continuous'
  distance_m: number
  sample_spacing_m: number
  points: TerrainProfilePoint[]
  sources: ContextSource[]
  warnings_uk: string[]
  land_cover_trace?: LandCoverTrace | null
  surface_observation_profile?: SurfaceProfileSummary | null
}
