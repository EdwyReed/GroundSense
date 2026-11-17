import { expect, it } from 'vitest'
import { closestPolylineChainage, pointAtChainage, sectionForChainage } from './transectSelection'

const line: [number, number][] = [[10, 59], [10.01, 59], [10.01, 59.01]]

it('projects a point onto the closest polyline segment and returns bounded chainage', () => {
  const result = closestPolylineChainage(line, { longitude: 10.008, latitude: 59.002 })
  expect(result).not.toBeNull()
  expect(result!.chainage_m).toBeGreaterThan(500)
  expect(result!.chainage_m).toBeLessThan(1500)
  expect(result!.point.longitude).toBeCloseTo(10.01, 6)
  expect(result!.point.latitude).toBeCloseTo(59.002, 6)
})

it('clamps endpoint projections and interpolates the same earth-radius convention', () => {
  expect(closestPolylineChainage(line, { longitude: 9, latitude: 59 })?.chainage_m).toBe(0)
  const end = closestPolylineChainage(line, { longitude: 11, latitude: 60 })!
  const atEnd = pointAtChainage(line, end.chainage_m)!
  expect(atEnd.longitude).toBeCloseTo(10.01, 6)
  expect(atEnd.latitude).toBeCloseTo(59.01, 6)
})

it('returns the owning server section only for a chainage inside its interval', () => {
  const sections = [{ index: 0, from_m: 0, to_m: 100 }, { index: 1, from_m: 100, to_m: 200 }]
  expect(sectionForChainage(sections, 100)?.index).toBe(0)
  expect(sectionForChainage(sections, 100, 1)?.index).toBe(1)
  expect(sectionForChainage(sections, 50, 1)?.index).toBe(0)
  expect(sectionForChainage(sections, 201)).toBeNull()
})

it.each([-1, 1e9])('rejects an out-of-line requested position rather than silently clamping: %s', chainage => {
  expect(pointAtChainage(line, chainage)).toBeNull()
})

it('bounds projection and interpolation before walking an oversized or overlong geometry', () => {
  const tooMany: [number, number][] = Array.from({ length: 257 }, (_, i) => [10 + i * .000001, 59])
  const tooLong: [number, number][] = [[10, 59], [11, 59]]
  for (const coordinates of [tooMany, tooLong]) {
    expect(closestPolylineChainage(coordinates, { longitude: 10, latitude: 59 })).toBeNull()
    expect(pointAtChainage(coordinates, 0)).toBeNull()
  }
})
