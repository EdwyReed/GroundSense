// @vitest-environment jsdom
import { createApp, h, nextTick, ref } from 'vue'
import { expect, it, vi } from 'vitest'
import SectionContext from './SectionContext.vue'

const planId = 'a'.repeat(32)
const flush = async () => { await Promise.resolve(); await nextTick() }
const point = (index: number) => ({ longitude: 10.75 + index / 100, latitude: 59.92 + index / 100 })
const soil = (index = 0) => ({ status: 'available', basis: 'hwsd_v2_smu_dominant_soil', requested_point: point(index), map_unit_id: 10124, wrb_code: index ? 'RTgl' : 'PZal', wrb_name: index ? 'Gleyic Retisols' : 'Albic Podzols', share_percent: 70, resolution_arc_seconds: 30, temporal_scope: 'static_reference', classification_system: 'WRB 2022', spatial_scope: 'soil_mapping_unit' })
const data = (index = 0) => ({
  plan_id: planId, route_id: 'transect-1', section_index: index, trip_date: '2026-10-26', status: 'partial', synthetic: false,
  evidence_scope: 'point_sample', coverage: 'not_continuous', soil_type: soil(index),
  sections: [0, 1, 2].map(i => ({ index: i, from_m: i * 1000, to_m: (i + 1) * 1000, point: point(i), geometry: { type: 'LineString', coordinates: [[10.74, 59.91], [10.78, 59.95]] } })),
  ground_composition: { status: 'partial', composition: { sand: 59.8, silt: 32.3, clay: 3.8 }, composition_depth_cm: [0, 5], support_m: 250, closure: { total_percent: 95.9, normalized: false } },
  sources: [{ id: 'hwsd-v2', product: 'Harmonized World Soil Database v2.0', status: 'available', extraction_scope: 'soil_mapping_unit', retrieved_at: '2026-10-26T12:00:00Z' }], warnings_uk: [],
})
const props = (client: any) => ({ client, planId, routeId: 'transect-1', tripDate: '2026-10-26', analysisKind: 'terrain_transect', vehicle: { kind: 'truck_6x6' as const, gross_mass_t: 20 } })

it('adds native reference soil inside collapsed terrain without replacing fractions or requesting another source', async () => {
  const client = { get: vi.fn(), post: vi.fn().mockResolvedValue(data()) }
  const root = document.createElement('div'), app = createApp(SectionContext, props(client)); app.mount(root)
  try {
    await flush()
    const terrain = root.querySelector<HTMLDetailsElement>('.terrain-details')!
    expect(terrain.open).toBe(false)
    expect(terrain.textContent).toContain('Albic Podzols')
    expect(terrain.textContent).toContain('PZal')
    expect(terrain.textContent).toContain('70%')
    expect(root.querySelector('.soil-composition')?.textContent).toContain('59,8%')
    expect(root.querySelector('.soil-composition')?.textContent).toContain('95,9%')
    expect(root.querySelector('.trip-request')?.textContent).toContain('Проїзність не оцінено')
    terrain.querySelector('summary')!.click(); await flush()
    expect(terrain.open).toBe(true)
    expect(client.post).toHaveBeenCalledOnce()
    expect(root.querySelector('.context-sources')?.textContent).toContain('Harmonized World Soil Database v2.0')
  } finally { app.unmount() }
})

it('binds soil to the current section point and discards a late older soil classification', async () => {
  let resolve!: (value: unknown) => void
  const selected = ref(0)
  const client = { get: vi.fn(), post: vi.fn().mockImplementationOnce(() => new Promise(value => { resolve = value })).mockResolvedValueOnce(data(1)) }
  const root = document.createElement('div'), app = createApp({ setup: () => () => h(SectionContext, { ...props(client), selectedSectionIndex: selected.value }) }); app.mount(root)
  try {
    selected.value = 1; await flush()
    expect(root.textContent).toContain('Gleyic Retisols')
    expect(root.textContent).not.toContain('Albic Podzols')
    resolve(data()); await flush()
    expect(root.textContent).toContain('Gleyic Retisols')
    expect(root.textContent).not.toContain('Albic Podzols')
    expect(client.post).toHaveBeenCalledTimes(2)
  } finally { app.unmount() }
})

it('does not display a valid class for a different point even when the enclosing context binding matches', async () => {
  const client = { get: vi.fn(), post: vi.fn().mockResolvedValue({ ...data(1), soil_type: soil(0) }) }
  const root = document.createElement('div'), app = createApp(SectionContext, { ...props(client), selectedSectionIndex: 1 }); app.mount(root)
  try {
    await flush()
    expect(root.textContent).not.toContain('Albic Podzols')
    expect(root.textContent).not.toContain('Gleyic Retisols')
    expect(root.textContent).toContain('Проїзність не оцінено')
    expect(client.post).toHaveBeenCalledOnce()
  } finally { app.unmount() }
})

it('never renders a reference soil card in the legacy road inspector', async () => {
  const client = { get: vi.fn(), post: vi.fn().mockResolvedValue(data()) }
  const root = document.createElement('div'), app = createApp(SectionContext, { ...props(client), analysisKind: undefined }); app.mount(root)
  try {
    await flush()
    expect(root.textContent).not.toContain('Albic Podzols')
    expect(root.querySelector('details.terrain-details')).toBeNull()
  } finally { app.unmount() }
})
