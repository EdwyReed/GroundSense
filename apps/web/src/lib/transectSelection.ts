import type { LngLat } from './routeTypes'

const EARTH_RADIUS_M = 6371000
const radians = (degrees: number) => degrees * Math.PI / 180

function valid(point: [number, number] | LngLat): boolean {
  const longitude = Array.isArray(point) ? point[0] : point.longitude
  const latitude = Array.isArray(point) ? point[1] : point.latitude
  return Number.isFinite(longitude) && Number.isFinite(latitude) && longitude >= -180 && longitude <= 180 && latitude >= -90 && latitude <= 90
}

export function segmentLength(a: [number, number], b: [number, number]): number {
  const dLat = radians(b[1] - a[1]), dLng = radians(b[0] - a[0])
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(radians(a[1])) * Math.cos(radians(b[1])) * Math.sin(dLng / 2) ** 2
  return 2 * EARTH_RADIUS_M * Math.atan2(Math.sqrt(h), Math.sqrt(1 - h))
}

function boundedLine(coordinates: [number, number][]) {
  if (!Array.isArray(coordinates) || coordinates.length < 2 || coordinates.length > 256 || !coordinates.every(point => Array.isArray(point) && point.length === 2 && valid(point))) return null
  const lengths = coordinates.slice(1).map((point, i) => segmentLength(coordinates[i], point))
  const total = lengths.reduce((sum, length) => sum + length, 0)
  return Number.isFinite(total) && total > 0 && total <= 20000 ? { lengths, total } : null
}

export function pointAtChainage(coordinates: [number, number][], chainage_m: number): LngLat | null {
  const line = boundedLine(coordinates)
  if (!line || !Number.isFinite(chainage_m) || chainage_m < 0 || chainage_m > line.total + 1e-6) return null
  let remaining = Math.min(line.total, chainage_m)
  for (let i = 1; i < coordinates.length; i++) {
    const a = coordinates[i - 1], b = coordinates[i], length = line.lengths[i - 1]
    if (length === 0) continue
    if (remaining <= length || i === coordinates.length - 1) {
      const fraction = Math.min(1, remaining / length)
      return { longitude: a[0] + (b[0] - a[0]) * fraction, latitude: a[1] + (b[1] - a[1]) * fraction }
    }
    remaining -= length
  }
  const end = coordinates.at(-1)!
  return { longitude: end[0], latitude: end[1] }
}

export function closestPolylineChainage(coordinates: [number, number][], target: LngLat): { chainage_m: number; point: LngLat } | null {
  if (!boundedLine(coordinates) || !target || !valid(target)) return null
  const latitudeScale = Math.cos(radians(target.latitude)) * EARTH_RADIUS_M * Math.PI / 180
  const longitudeScale = latitudeScale
  const latitudeMeters = EARTH_RADIUS_M * Math.PI / 180
  let before = 0, best: { chainage_m: number; point: LngLat; distance2: number } | null = null
  for (let i = 1; i < coordinates.length; i++) {
    const a = coordinates[i - 1], b = coordinates[i], length = segmentLength(a, b)
    const ax = (a[0] - target.longitude) * longitudeScale, ay = (a[1] - target.latitude) * latitudeMeters
    const bx = (b[0] - target.longitude) * longitudeScale, by = (b[1] - target.latitude) * latitudeMeters
    const dx = bx - ax, dy = by - ay, denominator = dx * dx + dy * dy
    const fraction = denominator === 0 ? 0 : Math.max(0, Math.min(1, -(ax * dx + ay * dy) / denominator))
    const x = ax + dx * fraction, y = ay + dy * fraction
    const point = { longitude: a[0] + (b[0] - a[0]) * fraction, latitude: a[1] + (b[1] - a[1]) * fraction }
    const candidate = { chainage_m: before + length * fraction, point, distance2: x * x + y * y }
    if (!best || candidate.distance2 < best.distance2) best = candidate
    before += length
  }
  return best && { chainage_m: best.chainage_m, point: best.point }
}

export function sectionForChainage<T extends { index?: number; from_m: number; to_m: number }>(sections: T[], chainage_m: number, preferredIndex?: number): T | null {
  if (!Number.isFinite(chainage_m)) return null
  const contains = (section: T) => Number.isFinite(section.from_m) && Number.isFinite(section.to_m) && chainage_m >= section.from_m && chainage_m <= section.to_m
  // The server accepts a shared endpoint for either adjacent section. Keep an
  // explicit range selection instead of silently moving it to its neighbour.
  return sections.find(section => preferredIndex !== undefined && section.index === preferredIndex && contains(section)) || sections.find(contains) || null
}
