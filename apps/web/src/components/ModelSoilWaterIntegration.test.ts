// @vitest-environment jsdom
import { createApp, h, nextTick, ref } from 'vue'
import { expect, it, vi } from 'vitest'
import SectionContext from './SectionContext.vue'

const planId = 'a'.repeat(32)
const point = { latitude: 59.98500020992624, longitude: 10.733331822658165 }
const digest = 'sha256:4ef282407d6e88b8414b9381349b45c8c1feb3a82988416697e83db9decda4b4'
const layer = (variable: string, from_cm: number, to_cm: number) => ({ variable, from_cm, to_cm, status: 'available', min_m3_m3: 0.296, max_m3_m3: 0.34, known_samples: 24, expected_samples: 24 })
const soilWater = () => ({ date: '2026-10-26', timezone: 'UTC', basis: 'weather_model_not_field_observation', status: 'available', source_id: 'open-meteo-icon-global', model: 'icon_global', source_sha256: digest, unit: 'm³/m³', requested_point: point, grid_point: { latitude: 60, longitude: 10.75 }, layers: [layer('soil_moisture_0_to_1cm', 0, 1), layer('soil_moisture_1_to_3cm', 1, 3), layer('soil_moisture_3_to_9cm', 3, 9)] })
const day = () => ({ date: '2026-10-26', timezone: 'UTC', basis: 'weather_model_not_field_observation', status: 'available', precipitation: { status: 'available', total_mm: 0, known_intervals: 24, expected_intervals: 24 }, soil_temperature: { status: 'available', min_c: 0, max_c: 1, known_samples: 24, expected_samples: 24, at_or_below_zero_samples: 1 }, snow_depth: { status: 'available', min_m: 0, max_m: 0, known_samples: 24, expected_samples: 24 } })
const fixture = (tripDate = '2026-10-26') => ({
  plan_id: planId, route_id: 'route-1', section_index: 0, trip_date: tripDate, status: 'partial', synthetic: false, evidence_scope: 'point_sample', coverage: 'not_continuous',
  sections: [0, 1, 2].map(index => ({ index, from_m: index * 1000, to_m: (index + 1) * 1000, point, geometry: { type: 'LineString', coordinates: [[10.73, 59.98], [10.74, 59.99]] } })),
  terrain: { elevation_m: 32.8, surface_kind: 'DSM', support_m: 30 }, weather: { day_summary: day(), soil_water: soilWater(), source: { id: 'open-meteo-icon-global', content_sha256: digest } }, sources: [], warnings_uk: [],
})
const flush = async () => { await Promise.resolve(); await nextTick() }

it('puts the closed soil-water disclosure after existing day weather with no additional request', async () => {
  const client = { get: vi.fn(), post: vi.fn().mockResolvedValue(fixture()) }
  const root = document.createElement('div'), app = createApp(SectionContext, { client, planId, routeId: 'route-1', tripDate: '2026-10-26', analysisKind: 'terrain_transect' }); app.mount(root)
  try {
    await flush()
    const weather = root.querySelector('.weather-day')!, disclosure = root.querySelector<HTMLDetailsElement>('.model-soil-water')!
    expect(disclosure).not.toBeNull(); expect(disclosure.open).toBe(false)
    expect(weather.contains(disclosure)).toBe(true)
    expect(weather.textContent!.indexOf('Модельна вода в ґрунті')).toBeGreaterThan(weather.textContent!.indexOf('Погода на дату'))
    disclosure.querySelector('summary')!.click(); await flush()
    expect(client.post).toHaveBeenCalledOnce()
  } finally { app.unmount() }
})

it('removes the old offroad standalone 0–1cm terrain metric while preserving the road branch', async () => {
  const offroadClient = { get: vi.fn(), post: vi.fn().mockResolvedValue(fixture()) }
  const roadClient = { get: vi.fn(), post: vi.fn().mockResolvedValue(fixture()) }
  const offroadRoot = document.createElement('div'), offroad = createApp(SectionContext, { client: offroadClient, planId, routeId: 'route-1', tripDate: '2026-10-26', analysisKind: 'terrain_transect' }); offroad.mount(offroadRoot)
  const roadRoot = document.createElement('div'), road = createApp(SectionContext, { client: roadClient, planId, routeId: 'route-1', tripDate: '2026-10-26' }); road.mount(roadRoot)
  try {
    await flush()
    expect(offroadRoot.querySelector('.context-metrics')?.textContent).not.toContain('Вологість 0–1 см')
    expect(roadRoot.querySelector('.context-metrics')?.textContent).toContain('Вологість 0–1 см')
  } finally { offroad.unmount(); road.unmount() }
})

it('clears old soil-water data immediately when the selected trip date changes', async () => {
  const tripDate = ref('2026-10-26')
  let resolveNext!: (value: unknown) => void
  const client = { get: vi.fn(), post: vi.fn().mockResolvedValueOnce(fixture()).mockImplementationOnce(() => new Promise(resolve => { resolveNext = resolve })) }
  const root = document.createElement('div'), app = createApp({ setup: () => () => h(SectionContext, { client, planId, routeId: 'route-1', tripDate: tripDate.value, analysisKind: 'terrain_transect' }) }); app.mount(root)
  try {
    await flush(); expect(root.querySelector('.model-soil-water')).not.toBeNull()
    tripDate.value = '2026-10-27'; await flush()
    expect(root.querySelector('.model-soil-water')).toBeNull()
    resolveNext(fixture('2026-10-27')); await flush()
  } finally { app.unmount() }
})

it.each([undefined, null])('keeps missing offroad soil water as a closed unknown disclosure: %s', async soil_water => {
  const data = fixture()
  Object.assign(data.weather, { soil_water })
  const client = { get: vi.fn(), post: vi.fn().mockResolvedValue(data) }
  const root = document.createElement('div'), app = createApp(SectionContext, { client, planId, routeId: 'route-1', tripDate: '2026-10-26', analysisKind: 'terrain_transect' }); app.mount(root)
  try {
    await flush()
    const disclosure = root.querySelector<HTMLDetailsElement>('.model-soil-water')
    expect(disclosure).not.toBeNull()
    expect(disclosure!.open).toBe(false)
    expect(disclosure!.textContent).toContain('Модельні дані про воду в ґрунті для обраної точки й дати не узгоджено.')
    expect(disclosure!.querySelectorAll('.soil-water-layer')).toHaveLength(0)
    expect(client.post).toHaveBeenCalledOnce()
  } finally { app.unmount() }
})

it('does not add the soil-water disclosure to the legacy road weather card', async () => {
  const client = { get: vi.fn(), post: vi.fn().mockResolvedValue(fixture()) }
  const root = document.createElement('div'), app = createApp(SectionContext, { client, planId, routeId: 'route-1', tripDate: '2026-10-26' }); app.mount(root)
  try {
    await flush()
    expect(root.querySelector('.weather-day')).not.toBeNull()
    expect(root.querySelector('.model-soil-water')).toBeNull()
  } finally { app.unmount() }
})
