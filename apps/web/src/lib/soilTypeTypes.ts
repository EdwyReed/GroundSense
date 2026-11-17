import type { LngLat } from './routeTypes'

export type SoilTypeStatus = 'available' | 'partial' | 'unavailable'

export type SoilTypeData = {
  status: SoilTypeStatus
  basis: 'hwsd_v2_smu_dominant_soil'
  requested_point: LngLat | null
  map_unit_id: number | null
  wrb_code: string | null
  wrb_name: string | null
  share_percent: number | null
  resolution_arc_seconds: 30 | null
  temporal_scope: 'static_reference'
  classification_system: 'WRB 2022'
  spatial_scope: 'soil_mapping_unit'
}
