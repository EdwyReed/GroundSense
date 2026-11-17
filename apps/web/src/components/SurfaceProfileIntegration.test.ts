// @vitest-environment jsdom
import { createApp, nextTick } from 'vue'
import { expect, it, vi } from 'vitest'
import TerrainProfile from './TerrainProfile.vue'
import { segmentLength } from '../lib/transectSelection'
import type { RouteGeometry } from '../lib/routeTypes'

const geometry = (): RouteGeometry => ({ type: 'LineString', coordinates: [[10.73, 59.982], [10.732, 59.983]] })
const flush = async () => { await Promise.resolve(); await nextTick(); await Promise.resolve(); await nextTick() }
function fixture(): any {
  const line = geometry(), distance = segmentLength(line.coordinates[0], line.coordinates[1])
  const points = line.coordinates.map(([longitude, latitude], index) => ({ chainage_m: index ? distance : 0, point: { longitude, latitude }, elevation_m: index ? 10 : 0, land_cover_class: 30, land_cover_label: 'grassland' }))
  const samples = points.map((point, index) => ({ chainage_m: point.chainage_m, requested_point: point.point, scl_class: index ? 9 : 6, condition: index ? 'cloud' : 'water', status: index ? 'partial' : 'available' }))
  const digest = `sha256:${'c'.repeat(64)}`
  const summary = { status: 'partial', basis: 'sentinel2_l2a_scl_profile_points', coverage: 'discrete_points', assessment_date: '2026-10-26', retrieved_at: '2026-10-26T12:00:00Z', observed_at: '2026-10-25T10:35:00Z', scene_id: 'scene', scene_age_days: 1, resolution_m: 20, selection_scope: 'bounded_catalogue_result', source_content_sha256: digest, samples }
  const source = { id: 'sentinel-2-l2a', status: 'partial', extraction_scope: 'spaced_scene_classification_points', retrieved_at: summary.retrieved_at, observed_at: summary.observed_at, content_sha256: digest, data: { extraction_scope: 'spaced_scene_classification_points', assessment_date: summary.assessment_date, scene_id: summary.scene_id, samples } }
  return { plan_id: 'c'.repeat(32), route_id: 'transect-1', trip_date: '2026-10-26', status: 'partial', synthetic: false, evidence_scope: 'spaced_point_samples', coverage: 'not_continuous', distance_m: distance, sample_spacing_m: distance, points, sources: [source], warnings_uk: [], surface_observation_profile: summary }
}
async function mount(data: any, routeGeometry: RouteGeometry | undefined = geometry(), inspectionReady = true) {
  const client = { get: vi.fn(), post: vi.fn().mockResolvedValue(data) }, inspect = vi.fn()
  const root = document.createElement('div')
  const app = createApp(TerrainProfile, { client, planId: data.plan_id, routeId: data.route_id, tripDate: data.trip_date, routeGeometry, inspectionReady, onInspectPoint: inspect })
  app.mount(root); await flush()
  return { app, root, client, inspect }
}

it('opens the source disclosure locally and emits one trusted chainage selection', async () => {
  const data = fixture(), { app, root, client, inspect } = await mount(data)
  try {
    expect(root.querySelectorAll('[data-testid="surface-inspect"]')).toHaveLength(2)
    root.querySelector<HTMLDetailsElement>('.surface-profile')!.open = true; await flush()
    root.querySelectorAll<HTMLButtonElement>('[data-testid="surface-inspect"]')[1].click(); await flush()
    expect(inspect).toHaveBeenCalledExactlyOnceWith(data.distance_m)
    expect(client.post).toHaveBeenCalledExactlyOnceWith('/terrain-profile', { plan_id: data.plan_id, route_id: data.route_id })
  } finally { app.unmount() }
})

it('does not authenticate a short prefix profile as the full saved A to B line', async () => {
  const line = geometry(); line.coordinates[1] = [10.734, 59.984]
  const { app, root } = await mount(fixture(), line)
  try {
    expect(root.textContent).toContain('Клас води')
    expect(root.querySelectorAll('[data-testid="surface-inspect"]')).toHaveLength(0)
  } finally { app.unmount() }
})

it('does not enable selection from a self-consistent source point shifted off the saved line', async () => {
  const data = fixture(); data.points[1].point.latitude += 1e-6
  const { app, root } = await mount(data)
  try { expect(root.querySelectorAll('[data-testid="surface-inspect"]')).toHaveLength(0) }
  finally { app.unmount() }
})

it('selects a captured terrain-table point even when its DSM value is missing', async () => {
  const data = fixture(); data.points[1].elevation_m = null
  const { app, root, client, inspect } = await mount(data)
  try {
    const buttons = root.querySelectorAll<HTMLButtonElement>('[data-testid="terrain-inspect"]')
    expect(buttons).toHaveLength(2)
    expect(buttons[1].getAttribute('aria-label')).toContain('Відкрити точку')
    buttons[1].click(); await flush()
    expect(inspect).toHaveBeenCalledExactlyOnceWith(data.points[1].chainage_m)
    expect(client.post).toHaveBeenCalledTimes(1)
    expect(root.querySelectorAll('.profile-height-point')).toHaveLength(1)
    expect(root.querySelectorAll('.profile-evidence tbody tr')[1].textContent).toContain('—')
  } finally { app.unmount() }
})

it('opens the nearest existing profile sample from the plotted area without interpolation', async () => {
  const data = fixture(), { app, root, client, inspect } = await mount(data)
  try {
    const svg = root.querySelector('svg')!
    vi.spyOn(svg, 'getBoundingClientRect').mockReturnValue({ x: 0, y: 0, left: 0, top: 0, width: 320, height: 133, right: 320, bottom: 133, toJSON() {} })
    svg.dispatchEvent(new MouseEvent('mousemove', { bubbles: true, clientX: 300, clientY: 30 }))
    expect(inspect).not.toHaveBeenCalled()
    svg.dispatchEvent(new MouseEvent('click', { bubbles: true, clientX: 300, clientY: 30 }))
    await flush()
    expect(inspect).toHaveBeenCalledExactlyOnceWith(data.points[1].chainage_m)
    expect(client.post).toHaveBeenCalledTimes(1)
    expect(root.textContent).toContain('найближчу точку вибірки')
  } finally { app.unmount() }
})

it.each(['foreign_geometry', 'shifted_sample', 'sections_not_ready'])('keeps terrain navigation read-only for %s', async fault => {
  const data = fixture(), line = geometry()
  if (fault === 'foreign_geometry') line.coordinates[1][0] += 0.001
  if (fault === 'shifted_sample') data.points[1].point.latitude += 0.000001
  const { app, root, inspect } = await mount(data, line, fault !== 'sections_not_ready')
  try {
    expect(root.querySelectorAll('[data-testid="terrain-inspect"]')).toHaveLength(0)
    expect(root.querySelector('.profile-selectable')).toBeNull()
    const svg = root.querySelector('svg')!
    vi.spyOn(svg, 'getBoundingClientRect').mockReturnValue({ left: 0, top: 0, width: 320, height: 133 } as DOMRect)
    svg.dispatchEvent(new MouseEvent('click', { bubbles: true, clientX: 300, clientY: 30 }))
    expect(inspect).not.toHaveBeenCalled()
  } finally { app.unmount() }
})

it.each([[0, 30, 0, 320], [100, 130, 0, 320], [300, 30, 2, 320], [300, 30, 0, 0]])('ignores graph margins/right-click/zero-size: %o', async (clientX, clientY, button, width) => {
  const { app, root, inspect } = await mount(fixture())
  try {
    const svg = root.querySelector('svg')!
    vi.spyOn(svg, 'getBoundingClientRect').mockReturnValue({ left: 0, top: 0, width, height: 133 } as DOMRect)
    svg.dispatchEvent(new MouseEvent('click', { bubbles: true, clientX, clientY, button }))
    expect(inspect).not.toHaveBeenCalled()
  } finally { app.unmount() }
})
