// @vitest-environment jsdom
import { createApp, h, nextTick, reactive } from 'vue'
import { expect, it, vi } from 'vitest'
import TerrainProfile from './TerrainProfile.vue'
import { ApiError } from '../lib/api'

const flush = async () => { await Promise.resolve(); await nextTick(); await Promise.resolve(); await nextTick() }
const planId = 'c'.repeat(32)
const fixture = (id = planId) => ({
  plan_id: id, route_id: 'transect-1', trip_date: '2026-10-26', synthetic: false, status: 'partial',
  evidence_scope: 'spaced_point_samples', coverage: 'not_continuous', distance_m: 750, sample_spacing_m: 250,
  points: [0, 250, 500, 750].map((chainage_m, i) => ({ chainage_m, point: { longitude: 10.73 + i * .001, latitude: 59.982 }, elevation_m: [0, -5, null, 20][i], land_cover_class: [30, 90, null, 80][i], land_cover_label: ['grassland', 'herbaceous_wetland', null, 'permanent_water'][i] })),
  sources: [{ id: 'copernicus-glo-30', status: 'partial', product: 'GLO-30 DSM' }, { id: 'esa-worldcover', status: 'partial', product: 'WorldCover 2021' }], warnings_uk: ['Вибірка, не суцільне покриття.'],
})

const traceFixture = () => ({
  status: 'partial', evidence_scope: 'intersected_raster_cells', coverage: 'centerline_only', reference_year: 2021, resolution_m: 10,
  distance_m: 750, known_m: 500, unknown_m: 250, cell_count: 3, tile_attempts: 1,
  segments: [
    { start_m: 0, end_m: 250, class_code: 30, label: 'grassland', geometry: { type: 'LineString', coordinates: [[10.73, 59.982], [10.731, 59.982]] } },
    { start_m: 250, end_m: 500, class_code: null, label: null, geometry: { type: 'LineString', coordinates: [[10.731, 59.982], [10.732, 59.982]] } },
    { start_m: 500, end_m: 750, class_code: 80, label: 'permanent_water', geometry: { type: 'LineString', coordinates: [[10.732, 59.982], [10.733, 59.982]] } },
  ], sources: [{ id: 'esa-worldcover', status: 'partial', product: 'WorldCover 2021' }], warnings_uk: ['Лише лінія · не коридор'],
})

it('emits the validated current WorldCover trace from the profile response without another request', async () => {
  const onTrace = vi.fn(), data = { ...fixture(), land_cover_trace: traceFixture() }
  const client = { get: vi.fn(), post: vi.fn().mockResolvedValue(data) }
  const root = document.createElement('div'); const app = createApp(TerrainProfile, { client, planId, routeId: 'transect-1', tripDate: '2026-10-26', onTrace }); app.mount(root)
  try {
    await flush()
    expect(client.post).toHaveBeenCalledTimes(1)
    expect(onTrace).toHaveBeenLastCalledWith(data.land_cover_trace)
  } finally { app.unmount() }
})

it('renders spaced DSM samples and static cover without joining an elevation gap or dropping zero', async () => {
  const client = { get: vi.fn(), post: vi.fn().mockResolvedValue(fixture()) }
  const root = document.createElement('div'); const app = createApp(TerrainProfile, { client, planId, routeId: 'transect-1', tripDate: '2026-10-26' }); app.mount(root)
  try {
    await flush()
    expect(client.post).toHaveBeenCalledWith('/terrain-profile', { plan_id: planId, route_id: 'transect-1' })
    expect(root.textContent).toContain('Висота вздовж A → B')
    expect(root.textContent).toContain('3 / 4')
    expect(root.textContent).toContain('250 м')
    expect(root.textContent).toContain('2021')
    expect(root.textContent).toContain('не суцільне покриття')
    expect(root.querySelectorAll('.profile-height-point')).toHaveLength(3)
    expect(root.querySelector('.profile-trace')?.getAttribute('d')?.match(/M/g)).toHaveLength(2)
    expect(root.querySelectorAll('.profile-cover-point')).toHaveLength(4)
    expect(root.querySelector('svg')?.textContent).toContain('0,0 м')
    expect(root.querySelector('svg')?.textContent).toContain('-5,0 м')
    expect(root.querySelector('svg')?.textContent).toContain('Водно-болотні угіддя')
    expect(root.querySelector('.profile-evidence')?.textContent).toContain('GLO-30 DSM')
    expect(root.querySelectorAll('.profile-evidence tbody tr')).toHaveLength(4)
  } finally { app.unmount() }
})

it('does not restore an old profile after the trip plan changes', async () => {
  let resolveOld!: (value: unknown) => void
  const newId = 'd'.repeat(32), nextProfile = fixture(newId)
  nextProfile.points[0].elevation_m = 99
  const client = { get: vi.fn(), post: vi.fn().mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve })).mockResolvedValueOnce(nextProfile) }
  const binding = reactive({ client, planId, routeId: 'transect-1', tripDate: '2026-10-26' })
  const root = document.createElement('div'); const app = createApp({ render: () => h(TerrainProfile, binding) }); app.mount(root)
  try {
    binding.planId = newId; await flush()
    expect(root.querySelector('svg')?.textContent).toContain('99,0 м')
    resolveOld(fixture()); await flush()
    expect(root.querySelector('svg')?.textContent).toContain('99,0 м')
  } finally { app.unmount() }
})

it.each([
  ['a foreign endpoint', (trace: any) => { trace.segments[0].geometry.coordinates[0] = [0, 0] }],
  ['a gap between spans', (trace: any) => { trace.segments[1].start_m = 251 }],
  ['an invalid native class', (trace: any) => { trace.segments[0].class_code = 77 }],
  ['a numeric string instead of a native class', (trace: any) => { trace.segments[0].class_code = '30' }],
  ['known metres that include unknown spans', (trace: any) => { trace.known_m = 750; trace.unknown_m = 0 }],
])('rejects %s instead of emitting it to the map', async (_name, corrupt) => {
  const trace = traceFixture(); corrupt(trace)
  const onTrace = vi.fn(), client = { get: vi.fn(), post: vi.fn().mockResolvedValue({ ...fixture(), land_cover_trace: trace }) }
  const root = document.createElement('div'); const app = createApp(TerrainProfile, { client, planId, routeId: 'transect-1', tripDate: '2026-10-26', onTrace }); app.mount(root)
  try { await flush(); expect(onTrace).toHaveBeenLastCalledWith(null); expect(root.querySelector('.trace-summary')).toBeNull() } finally { app.unmount() }
})

it.each([{ plan_id: 'foreign' }, { route_id: 'another' }, { trip_date: '2026-10-27' }, { coverage: 'continuous' }])('rejects a profile with a mismatched trip/scope: %o', async override => {
  const client = { get: vi.fn(), post: vi.fn().mockResolvedValue({ ...fixture(), ...override }) }
  const root = document.createElement('div'); const app = createApp(TerrainProfile, { client, planId, routeId: 'transect-1', tripDate: '2026-10-26' }); app.mount(root)
  try {
    await flush()
    expect(root.querySelector('svg')).toBeNull()
    expect(root.querySelector('[role=alert]')).not.toBeNull()
  } finally { app.unmount() }
})

it.each([404, 503])('offers the correct recovery for HTTP%s without accepting fabricated samples', async status => {
  const refresh = vi.fn()
  const client = { get: vi.fn(), post: vi.fn().mockRejectedValueOnce(new ApiError(status, 'provider detail')).mockResolvedValueOnce(fixture()) }
  const root = document.createElement('div'); const app = createApp(TerrainProfile, { client, planId, routeId: 'transect-1', tripDate: '2026-10-26', onRefresh: refresh }); app.mount(root)
  try {
    await flush()
    expect(root.querySelector('svg')).toBeNull()
    expect(root.textContent).not.toContain('provider detail')
    root.querySelector<HTMLButtonElement>('.profile-retry')!.click(); await flush()
    if (status === 404) {
      expect(refresh).toHaveBeenCalledOnce()
      expect(client.post).toHaveBeenCalledOnce()
    } else {
      expect(refresh).not.toHaveBeenCalled()
      expect(client.post).toHaveBeenCalledTimes(2)
      expect(root.querySelector('svg')).not.toBeNull()
    }
  } finally { app.unmount() }
})

it('adds a source-bound closed satellite disclosure without another profile request', async () => {
  const data: any = fixture()
  const samples = data.points.map((point: any, index: number) => ({ chainage_m: point.chainage_m, requested_point: point.point, scl_class: index ? 9 : 6, condition: index ? 'cloud' : 'water', status: index ? 'partial' : 'available' }))
  data.surface_observation_profile = { status: 'partial', basis: 'sentinel2_l2a_scl_profile_points', coverage: 'discrete_points', assessment_date: '2026-10-26', retrieved_at: '2026-10-26T12:00:00Z', observed_at: '2026-10-25T10:35:00Z', scene_id: 'scene', scene_age_days: 1, resolution_m: 20, selection_scope: 'bounded_catalogue_result', source_content_sha256: `sha256:${'a'.repeat(64)}`, samples }
  data.sources.push({ id: 'sentinel-2-l2a', status: 'partial', extraction_scope: 'spaced_scene_classification_points', retrieved_at: '2026-10-26T12:00:00Z', observed_at: '2026-10-25T10:35:00Z', content_sha256: `sha256:${'a'.repeat(64)}`, data: { extraction_scope: 'spaced_scene_classification_points', assessment_date: '2026-10-26', scene_id: 'scene', samples } })
  const client = { get: vi.fn(), post: vi.fn().mockResolvedValue(data) }
  const root = document.createElement('div'); const app = createApp(TerrainProfile, { client, planId, routeId: 'transect-1', tripDate: '2026-10-26' }); app.mount(root)
  try {
    await flush()
    expect(root.querySelector('.surface-profile')).not.toBeNull()
    expect((root.querySelector('.surface-profile') as HTMLDetailsElement).open).toBe(false)
    expect(client.post).toHaveBeenCalledTimes(1)
  } finally { app.unmount() }
})

it('labels a total source gap instead of drawing a flat zero-height profile', async () => {
  const data = fixture(); data.status = 'unavailable'
  data.points = data.points.map(point => ({ ...point, elevation_m: null, land_cover_class: null, land_cover_label: null }))
  const client = { get: vi.fn(), post: vi.fn().mockResolvedValue(data) }
  const root = document.createElement('div'); const app = createApp(TerrainProfile, { client, planId, routeId: 'transect-1', tripDate: '2026-10-26' }); app.mount(root)
  try {
    await flush()
    expect(root.textContent).toContain('Висоти не отримано')
    expect(root.querySelectorAll('.profile-height-point')).toHaveLength(0)
    expect(root.querySelector('.profile-trace')).toBeNull()
    expect(root.querySelector('.profile-retry')).not.toBeNull()
  } finally { app.unmount() }
})
