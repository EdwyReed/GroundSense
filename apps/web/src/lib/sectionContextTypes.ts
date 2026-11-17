import type { LngLat, RouteGeometry } from './routeTypes'
import type { WeatherDaySummary } from './weatherDayTypes'
import type { AntecedentPrecipitationSummary } from './antecedentPrecipitationTypes'
import type { SoilTypeData } from './soilTypeTypes'
import type { WeatherOutlookData } from './weatherOutlookTypes'
import type { ModelSoilWaterData } from './modelSoilWaterTypes'

export type RouteSection = {
  label_uk?: string
  basis?: string
  generalized?: boolean
  index: number
  from_m: number
  to_m: number
  point: LngLat
  geometry: RouteGeometry
}
export type ContextSource = {
  id: string
  extraction_scope?: string
  product?: string
  name?: string
  status?: string
  retrieved_at?: string | null
  content_sha256?: string | null
  observed_at?: string | null
  data?: unknown
}
export type SurfaceObservationData = {
  status: 'available' | 'partial' | 'unavailable'
  basis: string
  assessment_date: string | null
  requested_point: LngLat | null
  observed_at: string | null
  retrieved_at: string | null
  scene_age_days: number | null
  scene_id: string | null
  scl_class: number | null
  condition: string
  resolution_m: number | null
  selection_scope: string | null
}
export type SectionContextResponse = {
  plan_id: string
  route_id: string
  section_index: number
  trip_date: string
  status: string
  synthetic: false
  evidence_scope: 'point_sample'
  coverage: 'not_continuous'
  sections: RouteSection[]
  sample_selection?: { kind: 'line_chainage'; chainage_m: number; point: LngLat }
  land_cover?: { class?: number | null; label?: string | null; support_m?: number | null; reference_year?: number | null }
  terrain?: { elevation_m?: number | null; surface_kind?: string; support_m?: number | null }
  ground_composition?: { status: string; composition?: { sand: number | null; silt: number | null; clay: number | null }; support_m?: number | null; composition_depth_cm?: number[]; closure?: { total_percent: number | null; normalized: false } }
  local_terrain?: { slope_deg?: number | null }
  vegetation?: { tree_cover_percent?: number | null; valid_fraction?: number | null; footprint_m?: { width: number; height: number } | null; reference_year?: number }
  canopy_cover?: { percent: number | null; reference_year: number; resolution_m: number }
  surface_observation?: SurfaceObservationData | null
  soil_type?: SoilTypeData | null
  weather?: {
    status?: string
    assessment_date?: string
    day_summary?: WeatherDaySummary
    outlook?: WeatherOutlookData | null
    antecedent_precipitation?: AntecedentPrecipitationSummary
    soil_water?: ModelSoilWaterData | null
    units?: Record<string, string>
    series?: Array<{ time: string; [name: string]: unknown }>
    source?: ContextSource
  }
  sources: ContextSource[]
  warnings_uk: string[]
}
