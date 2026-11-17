import type { ContextSource } from './sectionContextTypes'
import type { LngLat } from './routeTypes'

export const WORLD_COVER_CLASSES = {
  10: { label: 'Дерева', color: '#548968' },
  20: { label: 'Чагарники', color: '#a0ac75' },
  30: { label: 'Трав’яний покрив', color: '#abc370' },
  40: { label: 'Рілля', color: '#d6b570' },
  50: { label: 'Забудова', color: '#9aa3b0' },
  60: { label: 'Розріджена рослинність', color: '#c7b7a6' },
  70: { label: 'Сніг / лід', color: '#b0cce3' },
  80: { label: 'Постійні водойми', color: '#529ce6' },
  90: { label: 'Водно-болотні угіддя', color: '#9584ba' },
  95: { label: 'Мангри', color: '#427b71' },
  100: { label: 'Мохи та лишайники', color: '#a8b69c' },
} as const

export type WorldCoverClass = keyof typeof WORLD_COVER_CLASSES
export type LandCoverTraceSegment = {
  start_m: number
  end_m: number
  class_code: WorldCoverClass | null
  label: string | null
  geometry: { type: 'LineString'; coordinates: [number, number][] }
}
export type LandCoverTrace = {
  status: 'available' | 'partial' | 'unavailable'
  evidence_scope: 'intersected_raster_cells'
  coverage: 'centerline_only'
  reference_year: 2021
  resolution_m: 10
  distance_m: number
  known_m: number
  unknown_m: number
  cell_count: number
  tile_attempts: number
  segments: LandCoverTraceSegment[]
  sources: ContextSource[]
  warnings_uk: string[]
}

export function coverClassification(classCode: number | null) {
  return classCode !== null && classCode in WORLD_COVER_CLASSES ? WORLD_COVER_CLASSES[classCode as WorldCoverClass] : { label: 'Покрив невідомий', color: '#8a929e' }
}

const finite = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value)
const sameCoordinate = (a: [number, number], b: [number, number]) => Math.abs(a[0] - b[0]) <= 1e-6 && Math.abs(a[1] - b[1]) <= 1e-6
const safeCoordinates = (coordinates: unknown): coordinates is [number, number][] => Array.isArray(coordinates) && coordinates.length >= 2 && coordinates.every(point => Array.isArray(point) && point.length === 2 && finite(point[0]) && finite(point[1]) && point[0] >= -180 && point[0] <= 180 && point[1] >= -90 && point[1] <= 90)

export function validateLandCoverTrace(value: unknown, expected: { distance_m: number; origin: LngLat; destination: LngLat }): LandCoverTrace | null {
  if (!value || typeof value !== 'object') return null
  const trace = value as Partial<LandCoverTrace>
  if (!['available', 'partial', 'unavailable'].includes(trace.status || '') || trace.evidence_scope !== 'intersected_raster_cells' || trace.coverage !== 'centerline_only' || trace.reference_year !== 2021 || trace.resolution_m !== 10 || !finite(trace.distance_m) || !finite(trace.known_m) || !finite(trace.unknown_m) || !Number.isInteger(trace.cell_count) || !Number.isInteger(trace.tile_attempts) || trace.cell_count! < 0 || trace.cell_count! > 8192 || trace.tile_attempts! < 0 || trace.tile_attempts! > 6 || !Array.isArray(trace.segments) || !Array.isArray(trace.sources) || !Array.isArray(trace.warnings_uk)) return null
  if (Math.abs(trace.distance_m - expected.distance_m) > .01 || trace.distance_m <= 0 || trace.known_m < 0 || trace.unknown_m < 0 || Math.abs(trace.known_m + trace.unknown_m - trace.distance_m) > .01 || !trace.segments.length) return null
  let end = 0
  let known = 0
  let previousCoordinates: [number, number][] | null = null
  for (const segment of trace.segments) {
    if (!segment || typeof segment !== 'object' || !finite(segment.start_m) || !finite(segment.end_m) || segment.start_m < 0 || segment.end_m <= segment.start_m || Math.abs(segment.start_m - end) > .01 || (segment.class_code !== null && (!Number.isInteger(segment.class_code) || !(segment.class_code in WORLD_COVER_CLASSES))) || (segment.class_code === null ? segment.label !== null : typeof segment.label !== 'string') || segment.geometry?.type !== 'LineString' || !safeCoordinates(segment.geometry.coordinates)) return null
    if (previousCoordinates && !sameCoordinate(previousCoordinates[previousCoordinates.length - 1], segment.geometry.coordinates[0])) return null
    if (segment.class_code !== null) known += segment.end_m - segment.start_m
    end = segment.end_m; previousCoordinates = segment.geometry.coordinates
  }
  const first = trace.segments[0].geometry.coordinates[0], last = previousCoordinates![previousCoordinates!.length - 1]
  if (Math.abs(known - trace.known_m) > .01 || Math.abs(end - trace.distance_m) > .01 || !sameCoordinate(first, [expected.origin.longitude, expected.origin.latitude]) || !sameCoordinate(last, [expected.destination.longitude, expected.destination.latitude])) return null
  return trace as LandCoverTrace
}
