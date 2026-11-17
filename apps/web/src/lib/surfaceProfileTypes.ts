import type { LngLat } from './routeTypes'

export type SurfaceProfileCondition = 'unknown' | 'vegetation' | 'not_vegetated' | 'water' | 'cloud' | 'shadow' | 'snow_ice'
export type SurfaceProfileStatus = 'available' | 'partial' | 'unavailable'

export type SurfaceProfileSample = {
  chainage_m: number
  requested_point: LngLat
  scl_class: number | null
  condition: SurfaceProfileCondition
  status: SurfaceProfileStatus
}

export type SurfaceProfileSummary = {
  status: SurfaceProfileStatus
  basis: 'sentinel2_l2a_scl_profile_points'
  coverage: 'discrete_points'
  assessment_date: string
  retrieved_at: string
  observed_at: string | null
  scene_id: string | null
  scene_age_days: number | null
  resolution_m: number | null
  selection_scope: 'bounded_catalogue_result'
  source_content_sha256: string | null
  samples: SurfaceProfileSample[]
}

export type SurfaceProfileSource = {
  id: 'sentinel-2-l2a'
  status: SurfaceProfileStatus
  extraction_scope: 'spaced_scene_classification_points'
  retrieved_at: string
  observed_at?: string | null
  content_sha256: string | null
  data?: {
    extraction_scope?: string
    assessment_date?: string
    scene_id?: string | null
    samples?: SurfaceProfileSample[]
  }
}
