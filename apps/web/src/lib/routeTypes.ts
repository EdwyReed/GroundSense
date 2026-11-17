export type LngLat = { longitude: number; latitude: number; label?: string }

export type VehicleKind = 'car' | 'truck_4x4' | 'truck_6x6'
export type RouteRequest = {
  origin: LngLat
  destination: LngLat
  trip_date: string
  vehicle: { kind: VehicleKind; gross_mass_t: number }
}

export type RouteGeometry = { type: 'LineString'; coordinates: [number, number][] }
export type RouteAlternative = {
  geometry_kind?: 'analysis_transect' | 'terrain_candidate'
  id: string
  name: string
  distance_m: number
  geometry: RouteGeometry
  conditions: { status: string; summary_uk: string }
  surface: { paved_m: number | null; unpaved_m: number | null }
  segments: unknown[]
}

export type RoutePlan = {
  analysis_kind?: 'terrain_transect' | 'terrain_candidate'
  plan_id?: string
  request: RouteRequest
  status: 'ready' | 'no_route' | 'unavailable'
  routes: RouteAlternative[]
  source?: { id: string; profile: string; retrieved_at: string }
  vehicle_assessment: 'not_assessed' | string
  date_assessment: 'not_assessed' | string
  synthetic: boolean
  warnings_uk: string[]
}

export type PlaceSearch = {
  places: LngLat[]
  source?: { id: string }
  status: 'ready' | string
}

export interface RouteApiClient {
  get<T>(path: string): Promise<T>
  post<T>(path: string, body: unknown): Promise<T>
}

export function isTerrainAnalysis(kind: string | undefined): boolean {
  return kind === 'terrain_transect' || kind === 'terrain_candidate'
}

export function isTerrainGeometry(kind: string | undefined): boolean {
  return kind === 'analysis_transect' || kind === 'terrain_candidate'
}
