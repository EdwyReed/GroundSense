// @vitest-environment jsdom
import { createApp, h, nextTick, ref } from 'vue'
import { expect, it, vi } from 'vitest'
import SectionContext from './SectionContext.vue'
import { ApiError } from '../lib/api'

const flush = async () => { await Promise.resolve(); await nextTick() }
const planId = 'a'.repeat(32)
const fixture = (sectionIndex = 0, label = 'herbaceous_wetland') => ({
  plan_id: planId, route_id: 'route-1', section_index: sectionIndex, trip_date: '2026-10-26', status: 'partial', synthetic: false,
  evidence_scope: 'point_sample', coverage: 'not_continuous',
  sections: [0, 1, 2].map(index => ({ index, from_m: index * 1000, to_m: (index + 1) * 1000, point: { longitude: 10.75, latitude: 59.92 }, geometry: { type: 'LineString', coordinates: [[10.74, 59.91], [10.76, 59.93]] } })),
  land_cover: { class: 90, label, support_m: 10, reference_year: 2021 },
  terrain: { elevation_m: 32.8, surface_kind: 'DSM', support_m: 30 },
  weather: { assessment_date: '2026-10-26', units: { soil_moisture_0_to_1cm: 'm³/m³', temperature_2m: '°C' }, series: [{ time: '2026-10-26T00:00:00Z', soil_moisture_0_to_1cm: .32, temperature_2m: 4.5 }], source: { id: 'open-meteo-icon-global', product: 'DWD ICON Global', retrieved_at: '2026-10-25T22:00:00Z' } },
  sources: [{ id: 'esa-worldcover', product: 'ESA WorldCover 2021', retrieved_at: '2026-10-25T22:00:00Z' }], warnings_uk: [],
})

it.each([1, 5, 8])('renders the actual %i server sections and accepts selection beyond index 2', async count => {
  const selected = count - 1
  const data = { ...fixture(selected), sections: Array.from({ length: count }, (_, index) => ({ ...fixture().sections[0]!, index, from_m: index * 73, to_m: (index + 1) * 73, label_uk: `Покрив ${index}` })) }
  const client = { get: vi.fn(), post: vi.fn().mockResolvedValue(data) }
  const root = document.createElement('div')
  const app = createApp(SectionContext, { client, planId, routeId: 'route-1', tripDate: '2026-10-26', selectedSectionIndex: selected }); app.mount(root)
  try {
    await flush()
    expect(client.post).toHaveBeenCalledWith('/route-context', { plan_id: planId, route_id: 'route-1', section_index: selected })
    expect(root.querySelectorAll('[data-section-index]')).toHaveLength(count)
    expect(root.querySelector(`[data-section-index="${selected}"]`)?.getAttribute('aria-pressed')).toBe('true')
    expect(root.textContent).toContain(`Покрив ${selected}`)
  } finally { app.unmount() }
})

it('loads selected-section context and distinguishes point/static/model evidence from road suitability', async () => {
  const client = { get: vi.fn(), post: vi.fn().mockResolvedValue(fixture()) }
  const root = document.createElement('div')
  const app = createApp(SectionContext, { client, planId, routeId: 'route-1', tripDate: '2026-10-26' }); app.mount(root)
  try {
    expect(client.post).toHaveBeenCalledWith('/route-context', { plan_id: planId, route_id: 'route-1', section_index: 0 })
    await flush()
    expect(root.textContent).toContain('Водно-болотні угіддя')
    expect(root.textContent).toContain('2021')
    expect(root.textContent).toContain('0,320')
    expect(root.textContent).toContain('м³/м³')
    expect(root.textContent).toContain('32,8')
    expect(root.textContent).toContain('не суцільна оцінка')
    expect(root.textContent).toContain('Проїзність не оцінено')
    expect(root.querySelector('.surface-observation')).toBeNull()
    expect(root.querySelectorAll('[data-section-index]')).toHaveLength(3)
  } finally { app.unmount() }
})

it('commits an explicit terrain range position once', async () => {
  const commit = vi.fn()
  const client = { get: vi.fn(), post: vi.fn().mockResolvedValueOnce(fixture()) }
  const root = document.createElement('div')
  const app = createApp(SectionContext, { client, planId, routeId: 'route-1', tripDate: '2026-10-26', analysisKind: 'terrain_transect', selectedSectionIndex: 0, onSelectChainage: commit }); app.mount(root)
  try {
    await flush()
    const range = root.querySelector<HTMLInputElement>('[data-testid="sample-chainage"]')!
    range.value = '400'; range.dispatchEvent(new Event('input', { bubbles: true })); await flush()
    expect(client.post).toHaveBeenCalledOnce()
    root.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })); await flush()
    expect(commit).toHaveBeenCalledExactlyOnceWith(400)
    expect(client.post).toHaveBeenCalledOnce()
  } finally { app.unmount() }
})

it('loads a controlled map section and emits its bound geometry without requesting on preview', async () => {
  const client = { get: vi.fn(), post: vi.fn().mockResolvedValue(fixture(2)) }
  const sections = vi.fn(), choose = vi.fn(), preview = vi.fn()
  const root = document.createElement('div')
  const app = createApp(SectionContext, { client, planId, routeId: 'route-1', tripDate: '2026-10-26', selectedSectionIndex: 2, onSections: sections, onSelectSection: choose, onPreviewSection: preview }); app.mount(root)
  try {
    expect(client.post).toHaveBeenCalledWith('/route-context', { plan_id: planId, route_id: 'route-1', section_index: 2 })
    await flush()
    expect(sections).toHaveBeenLastCalledWith(fixture(2).sections)
    expect(root.querySelector('[data-section-index="2"]')?.getAttribute('aria-pressed')).toBe('true')
    const first = root.querySelector<HTMLButtonElement>('[data-section-index="0"]')!
    first.dispatchEvent(new Event('mouseenter')); first.dispatchEvent(new Event('focus'))
    expect(preview).toHaveBeenLastCalledWith(0)
    first.dispatchEvent(new Event('mouseleave')); first.dispatchEvent(new Event('blur'))
    expect(preview).toHaveBeenLastCalledWith(null)
    expect(client.post).toHaveBeenCalledOnce()
    first.click(); await flush()
    expect(choose).toHaveBeenCalledWith(0)
    expect(client.post).toHaveBeenCalledOnce()
  } finally { app.unmount() }
})

it('changes a controlled section once and rejects old evidence and geometry on a late reply', async () => {
  let resolve!: (value: unknown) => void
  const selected = ref(0), loaded = vi.fn(), allSections = vi.fn()
  const client = { get: vi.fn(), post: vi.fn().mockImplementationOnce(() => new Promise(value => { resolve = value })).mockResolvedValueOnce(fixture(1, 'built_up')) }
  const root = document.createElement('div')
  const app = createApp({ setup: () => () => h(SectionContext, { client, planId, routeId: 'route-1', tripDate: '2026-10-26', selectedSectionIndex: selected.value, onSection: loaded, onSections: allSections }) }); app.mount(root)
  try {
    selected.value = 1; await flush()
    expect(client.post.mock.calls.map(call => call[1].section_index)).toEqual([0, 1])
    expect(loaded).toHaveBeenCalledWith(null)
    expect(loaded).toHaveBeenLastCalledWith(fixture(1).sections[1])
    const emissions = allSections.mock.calls.length
    resolve(fixture()); await flush()
    expect(allSections).toHaveBeenCalledTimes(emissions)
    expect(loaded).toHaveBeenLastCalledWith(fixture(1).sections[1])
    expect(root.textContent).toContain('Забудова')
    expect(root.textContent).not.toContain('Водно-болотні угіддя')
  } finally { app.unmount() }
})

it('keeps the new section when an earlier context reply arrives late', async () => {
  let resolve!: (value: unknown) => void
  const client = { get: vi.fn(), post: vi.fn().mockResolvedValueOnce(fixture()).mockImplementationOnce(() => new Promise(value => { resolve = value })).mockResolvedValueOnce(fixture(2, 'built_up')) }
  const root = document.createElement('div')
  const app = createApp(SectionContext, { client, planId, routeId: 'route-1', tripDate: '2026-10-26' }); app.mount(root)
  try {
    await flush()
    root.querySelector<HTMLButtonElement>('[data-section-index="1"]')!.click(); await flush()
    root.querySelector<HTMLButtonElement>('[data-section-index="2"]')!.click(); await flush()
    expect(root.textContent).toContain('Забудова')
    resolve(fixture(1)); await flush()
    expect(root.textContent).toContain('Забудова')
    expect(root.textContent).not.toContain('Водно-болотні угіддя')
  } finally { app.unmount() }
})

it('renders derived daily weather from the same context response without another provider request', async () => {
  const data = fixture()
  const day = { date: '2026-10-26', timezone: 'UTC', basis: 'weather_model_not_field_observation', status: 'available', precipitation: { status: 'available', total_mm: 2.4, known_intervals: 24, expected_intervals: 24 }, soil_temperature: { status: 'available', min_c: -1, max_c: 5, known_samples: 24, expected_samples: 24, at_or_below_zero_samples: 2 }, snow_depth: { status: 'available', min_m: 0, max_m: 0, known_samples: 24, expected_samples: 24 } }
  const client = { get: vi.fn(), post: vi.fn().mockResolvedValue({ ...data, weather: { ...data.weather, day_summary: day } }) }
  const root = document.createElement('div'); const app = createApp(SectionContext, { client, planId, routeId: 'route-1', tripDate: '2026-10-26' }); app.mount(root)
  try {
    await flush()
    expect(root.querySelector('.weather-day')?.textContent).toContain('2,4 мм')
    expect(root.querySelector('.day-snow dd')?.textContent).toBe('0,0 см')
    expect(root.textContent).toContain('0,320')
    expect(client.post).toHaveBeenCalledOnce()
  } finally { app.unmount() }
})

it('rejects a response whose trip binding does not match the current trip', async () => {
  const client = { get: vi.fn(), post: vi.fn().mockResolvedValue({ ...fixture(), trip_date: '2026-10-27' }) }
  const root = document.createElement('div')
  const app = createApp(SectionContext, { client, planId, routeId: 'route-1', tripDate: '2026-10-26' }); app.mount(root)
  try {
    await flush()
    expect(root.querySelector('[role="alert"]')).not.toBeNull()
    expect(root.textContent).not.toContain('Водно-болотні угіддя')
  } finally { app.unmount() }
})

it('shows soil, surface slope and neighbourhood tree fraction without claiming stem density', async () => {
  const client = { get: vi.fn(), post: vi.fn().mockResolvedValue({ ...fixture(), ground_composition: { status: 'available', composition: { sand: 41, silt: 38, clay: 21 }, support_m: 250, composition_depth_cm: [0, 5], closure: { total_percent: 100, normalized: false } }, local_terrain: { slope_deg: 12.3 }, vegetation: { tree_cover_percent: 84, valid_fraction: .9, footprint_m: { width: 236, height: 250 }, reference_year: 2021 } }) }
  const root = document.createElement('div'); const app = createApp(SectionContext, { client, planId, routeId: 'route-1', tripDate: '2026-10-26' }); app.mount(root)
  try {
    await flush()
    expect(root.textContent).toContain('Пісок: 41,0%')
    expect(root.textContent).toContain('Схил поверхні DSM')
    expect(root.textContent).toContain('12,3')
    expect(root.textContent).toContain('84,0%')
    expect(root.textContent).toContain('236 × 250 м')
    expect(root.textContent).toContain('Сума оцінок: 100,0%')
    expect(root.textContent).toContain('не щільність стовбурів')
    expect(root.textContent).not.toContain('Склад ґрунту не отримано')
  } finally { app.unmount() }
})

it('offers a new analysis instead of endlessly retrying an expired plan handle', async () => {
  const refresh = vi.fn()
  const client = { get: vi.fn(), post: vi.fn().mockRejectedValue(new ApiError(404, 'expired')) }
  const root = document.createElement('div'); const app = createApp(SectionContext, { client, planId, routeId: 'route-1', tripDate: '2026-10-26', onRefresh: refresh }); app.mount(root)
  try {
    await flush()
    expect(root.textContent).toContain('Строк дії плану минув')
    root.querySelector<HTMLButtonElement>('.context-retry')!.click(); await flush()
    expect(refresh).toHaveBeenCalledOnce()
    expect(client.post).toHaveBeenCalledOnce()
  } finally { app.unmount() }
})

it.each([{ percent: 77, label: '77,0%' }, { percent: 0, label: '0,0%' }, { percent: null, label: '—' }])('shows native canopy context separately from neighbourhood tree fraction: $percent', async ({ percent, label }) => {
  const client = { get: vi.fn(), post: vi.fn().mockResolvedValue({ ...fixture(), canopy_cover: { percent, reference_year: 2018, resolution_m: 10 }, vegetation: { tree_cover_percent: 100, reference_year: 2021 } }) }
  const root = document.createElement('div'); const app = createApp(SectionContext, { client, planId, routeId: 'route-1', tripDate: '2026-10-26' }); app.mount(root)
  try {
    await flush()
    const metric = root.querySelector('.canopy-metric')
    expect(metric?.textContent).toContain('Зімкнутість крон')
    expect(metric?.textContent).toContain(label)
    expect(metric?.textContent).toContain('2018')
    expect(root.textContent).toContain('100,0%')
    expect(root.textContent).toContain('Просвіти для техніки невідомі')
    if (percent !== null) expect(root.textContent).not.toContain('Зімкнутість крон невідома')
  } finally { app.unmount() }
})

it('binds a satellite scene to the selected server point and clears it across date and late-section changes', async () => {
  let resolveOld!: (value: unknown) => void
  const current = ref(0), tripDate = ref('2026-10-26')
  const scene = { status: 'available', basis: 'sentinel2_l2a_scl_point', assessment_date: '2026-10-26', requested_point: { latitude: 59.92, longitude: 10.75 }, observed_at: '2026-10-25T10:35:00Z', retrieved_at: '2026-10-26T12:00:00Z', scene_age_days: 1, scene_id: 'scene', scl_class: 6, condition: 'water', resolution_m: 20, selection_scope: 'bounded_catalogue_result' }
  const day = { date: '2026-10-26', timezone: 'UTC', basis: 'weather_model_not_field_observation', status: 'available', precipitation: { status: 'available', total_mm: 0, known_intervals: 24, expected_intervals: 24 }, soil_temperature: { status: 'available', min_c: 0, max_c: 1, known_samples: 24, expected_samples: 24, at_or_below_zero_samples: 1 }, snow_depth: { status: 'available', min_m: 0, max_m: 0, known_samples: 24, expected_samples: 24 } }
  const currentData = { ...fixture(0), weather: { ...fixture().weather, day_summary: day }, surface_observation: scene, sources: [{ id: 'sentinel-2-l2a', extraction_scope: 'scene_classification_point', product: 'Sentinel-2 L2A SCL', retrieved_at: '2026-10-26T12:00:00Z' }] }
  const client = { get: vi.fn(), post: vi.fn().mockResolvedValueOnce(currentData).mockImplementationOnce(() => new Promise(value => { resolveOld = value })).mockResolvedValueOnce({ ...fixture(1), trip_date: '2026-10-27', surface_observation: { ...scene, assessment_date: '2026-10-27', observed_at: '2026-10-27T10:35:00Z', retrieved_at: '2026-10-27T12:00:00Z', scene_age_days: 0 } }) }
  const root = document.createElement('div'); const app = createApp({ setup: () => () => h(SectionContext, { client, planId, routeId: 'route-1', tripDate: tripDate.value, selectedSectionIndex: current.value }) }); app.mount(root)
  try {
    await flush()
    expect(root.querySelector('.surface-observation')?.textContent).toContain('Клас SCL 6 · вода')
    expect(root.textContent.indexOf('Супутникове спостереження')).toBeLessThan(root.textContent.indexOf('Погода на дату'))
    expect(root.textContent).toContain('Sentinel-2 L2A SCL')
    current.value = 1; await flush()
    expect(root.querySelector('.surface-observation')).toBeNull()
    tripDate.value = '2026-10-27'; await flush()
    expect(root.querySelector('.surface-observation')?.textContent).toContain('2026-10-27 · UTC')
    expect(root.querySelector('.surface-observation')?.textContent).not.toContain('2026-10-25')
    resolveOld(currentData); await flush()
    expect(root.querySelector('.surface-observation')?.textContent).toContain('2026-10-27 · UTC')
    expect(root.querySelector('.surface-observation')?.textContent).not.toContain('2026-10-25')
    expect(client.post).toHaveBeenCalledTimes(3)
  } finally { app.unmount() }
})

it('puts plan vehicle and existing day/history weather before collapsed terrain only in offroad mode', async () => {
  const data = fixture()
  const day = { date: '2026-10-26', timezone: 'UTC', basis: 'weather_model_not_field_observation', status: 'available', precipitation: { status: 'available', total_mm: 2.4, known_intervals: 24, expected_intervals: 24 }, soil_temperature: { status: 'available', min_c: -1, max_c: 5, known_samples: 24, expected_samples: 24, at_or_below_zero_samples: 2 }, snow_depth: { status: 'available', min_m: 0, max_m: 0, known_samples: 24, expected_samples: 24 } }
  const antecedent = { date: '2026-10-26', timezone: 'UTC', basis: 'weather_model_not_field_observation', window_start: '2026-10-19', window_end_exclusive: '2026-10-26', window_days: 7, status: 'available', total_mm: 7, known_intervals: 168, expected_intervals: 168, days: Array.from({ length: 7 }, (_, i) => ({ date: `2026-10-${19 + i}`, status: 'available', total_mm: 1, known_intervals: 24, expected_intervals: 24 })) }
  const client = { get: vi.fn(), post: vi.fn().mockResolvedValue({ ...data, weather: { ...data.weather, day_summary: day, antecedent_precipitation: antecedent } }) }
  const root = document.createElement('div'), app = createApp(SectionContext, { client, planId, routeId: 'route-1', tripDate: '2026-10-26', analysisKind: 'terrain_transect', vehicle: { kind: 'truck_6x6', gross_mass_t: 20.25 } }); app.mount(root)
  try {
    await flush()
    expect(root.querySelector('.trip-request')?.textContent).toContain('Вантажівка 6×6 · 20,25 т')
    expect(root.querySelector('.trip-request')?.textContent).toContain('2026-10-26')
    expect(root.querySelector('.trip-request')?.textContent).toContain('Проїзність не оцінено')
    expect(root.querySelector('.trip-request')?.textContent).toContain('Поточне підтоплення')
    const terrain = root.querySelector<HTMLDetailsElement>('details.terrain-details')!
    expect(terrain).not.toBeNull(); expect(terrain.open).toBe(false)
    expect(terrain.contains(root.querySelector('.context-metrics'))).toBe(true)
    expect(root.querySelectorAll('.weather-day')).toHaveLength(1)
    expect(root.querySelector('.weather-day')!.compareDocumentPosition(terrain) & Node.DOCUMENT_POSITION_FOLLOWING).not.toBe(0)
    expect(root.querySelector('.day-precipitation')?.textContent).toContain('2,4 мм')
    expect(root.querySelector('.antecedent-total')?.textContent).toBe('7,0 мм')
    terrain.querySelector('summary')!.click(); await flush()
    expect(terrain.open).toBe(true)
    expect(terrain.textContent).toContain('Водно-болотні угіддя')
    expect(terrain.textContent).toContain('32,8')
    expect(root.querySelector('.context-sources')?.textContent).toContain('ESA WorldCover 2021')
    expect(client.post).toHaveBeenCalledOnce()
  } finally { app.unmount() }
})

it.each([undefined, { kind: 'truck_6x6', gross_mass_t: '20' }, { kind: 'truck_6x6', gross_mass_t: Number.NaN }, { kind: 'truck_6x6', gross_mass_t: 0 }, { kind: 'truck_6x6', gross_mass_t: -1 }, { kind: 'truck_6x6', gross_mass_t: Number.POSITIVE_INFINITY }, { kind: 'unknown', gross_mass_t: 20 }])('never invents a vehicle or mass from invalid offroad metadata: %o', async vehicle => {
  const client = { get: vi.fn(), post: vi.fn().mockResolvedValue(fixture()) }
  const root = document.createElement('div'), app = createApp(SectionContext, { client, planId, routeId: 'route-1', tripDate: '2026-10-26', analysisKind: 'terrain_transect', vehicle: vehicle as any }); app.mount(root)
  try {
    await flush()
    expect(root.querySelector('.trip-request')?.textContent).toContain('Параметри транспорту недоступні')
    expect(root.querySelector('.trip-request')?.textContent).not.toContain('20 т')
    expect(root.querySelector('.trip-request')?.textContent).toContain('Проїзність не оцінено')
  } finally { app.unmount() }
})

it('keeps the legacy road hierarchy and exposes out-of-range weather instead of another date', async () => {
  const client = { get: vi.fn(), post: vi.fn().mockResolvedValue({ ...fixture(), weather: { status: 'date_out_of_range' } }) }
  const root = document.createElement('div'), app = createApp(SectionContext, { client, planId, routeId: 'route-1', tripDate: '2026-10-26' }); app.mount(root)
  try {
    await flush()
    expect(root.querySelector('.trip-request')).toBeNull()
    expect(root.querySelector('details.terrain-details')).toBeNull()
    expect(root.querySelector('.context-metrics')).not.toBeNull()
    expect(root.querySelector('.weather-day')).toBeNull()
    expect(root.textContent).toContain('Дата поза горизонтом прогнозу')
  } finally { app.unmount() }
})

it('keeps an offroad out-of-range date visible outside the collapsed terrain without substituted weather', async () => {
  const client = { get: vi.fn(), post: vi.fn().mockResolvedValue({ ...fixture(), trip_date: '2026-11-05', weather: { status: 'date_out_of_range' } }) }
  const root = document.createElement('div'), app = createApp(SectionContext, { client, planId, routeId: 'route-1', tripDate: '2026-11-05', analysisKind: 'terrain_transect', vehicle: { kind: 'truck_6x6', gross_mass_t: 20 } }); app.mount(root)
  try {
    await flush()
    const terrain = root.querySelector<HTMLDetailsElement>('details.terrain-details')!
    const gap = [...root.querySelectorAll('.context-gap')].find(row => row.textContent?.includes('Дата поза горизонтом прогнозу'))!
    expect(terrain.open).toBe(false)
    expect(gap.textContent).toContain('Іншу дату не підставлено')
    expect(gap.closest('details')).toBeNull()
    expect(gap.compareDocumentPosition(terrain) & Node.DOCUMENT_POSITION_FOLLOWING).not.toBe(0)
    expect(root.querySelector('.trip-request')?.textContent).toContain('2026-11-05')
    expect(root.querySelector('.trip-request')?.textContent).toContain('Проїзність не оцінено')
    expect(root.querySelector('.weather-day')).toBeNull()
    expect(root.querySelector('.antecedent-total')).toBeNull()
    expect(client.post).toHaveBeenCalledOnce()
  } finally { app.unmount() }
})
