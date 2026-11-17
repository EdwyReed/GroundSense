// @vitest-environment jsdom
import { createApp, nextTick } from 'vue'
import { expect, it } from 'vitest'
import ModelSoilWater from './ModelSoilWater.vue'

const point = { latitude: 59.98500020992624, longitude: 10.733331822658165 }
const digest = 'sha256:4ef282407d6e88b8414b9381349b45c8c1feb3a82988416697e83db9decda4b4'
const layer = (variable: string, from_cm: number, to_cm: number, override = {}) => ({ variable, from_cm, to_cm, status: 'available', min_m3_m3: 0, max_m3_m3: 0.34, known_samples: 24, expected_samples: 24, ...override })
const valid = () => ({
  date: '2026-10-26', timezone: 'UTC', basis: 'weather_model_not_field_observation', status: 'available',
  source_id: 'open-meteo-icon-global', model: 'icon_global', source_sha256: digest, unit: 'm³/m³',
  requested_point: point, grid_point: { latitude: 60, longitude: 10.75 },
  layers: [layer('soil_moisture_0_to_1cm', 0, 1), layer('soil_moisture_1_to_3cm', 1, 3, { min_m3_m3: 0.298, max_m3_m3: 0.339 }), layer('soil_moisture_3_to_9cm', 3, 9, { min_m3_m3: 0.306, max_m3_m3: 0.341 })],
})

async function mount(soilWater: unknown, overrides: Record<string, unknown> = {}) {
  const root = document.createElement('div')
  const app = createApp(ModelSoilWater, { soilWater, selectedPoint: point, tripDate: '2026-10-26', sourceDigest: digest, ...overrides })
  app.mount(root); await nextTick()
  return { root, app }
}

it('shows three bound native model layers in one closed disclosure, including zero values', async () => {
  const { root, app } = await mount(valid())
  try {
    const details = root.querySelector<HTMLDetailsElement>('details.model-soil-water')!
    expect(details).not.toBeNull(); expect(details.open).toBe(false)
    expect(details.querySelector('summary')?.textContent).toBe('Модельна вода в ґрунті')
    expect(root.querySelectorAll('.soil-water-layer')).toHaveLength(3)
    expect(root.textContent).toContain('0–1 см')
    expect(root.textContent).toContain('0,000–0,340 м³/м³')
    expect(root.textContent).toContain('24 / 24')
    expect(root.textContent).toContain('ICON Global через Open-Meteo')
    expect(root.textContent).toContain('Запитана точка: 59,985000, 10,733332')
    expect(root.textContent).toContain('Комірка моделі: 60,000000, 10,750000')
    expect(root.textContent).toContain('не виміряна місцева поверхнева вологість')
    expect(root.textContent).toContain('не насичення, не несуча здатність і не дозвіл на рух')
    expect(root.textContent).toContain('Годинні значення API можуть бути інтерпольовані')
    expect(root.textContent).toContain('24 / 24 означає повноту ряду API, не незалежні спостереження')
    expect(root.textContent).not.toContain('розділь')
  } finally { app.unmount() }
})

it('labels partial ranges as known-point ranges without making a full-day claim', async () => {
  const data = valid(); data.status = 'partial'; data.layers[1] = layer('soil_moisture_1_to_3cm', 1, 3, { status: 'partial', known_samples: 12, min_m3_m3: 0.2, max_m3_m3: 0.3 })
  const { root, app } = await mount(data)
  try {
    expect(root.querySelectorAll('.soil-water-layer')[1]?.textContent).toContain('12 / 24')
    expect(root.querySelectorAll('.soil-water-layer')[1]?.textContent).toContain('серед відомих точок')
  } finally { app.unmount() }
})

it.each([
  ['wrong point', (data: any) => { data.requested_point = { ...point, latitude: 60 } }],
  ['wrong date', (data: any) => { data.date = '2026-10-27' }],
  ['wrong digest', (data: any) => { data.source_sha256 = digest.replace(/4$/, '5') }],
  ['wrong model', (data: any) => { data.model = 'ifs' }],
  ['wrong unit', (data: any) => { data.unit = '%' }],
  ['wrong layer order', (data: any) => { data.layers.reverse() }],
  ['wrong depth', (data: any) => { data.layers[0].to_cm = 2 }],
  ['wrong count', (data: any) => { data.layers[0].known_samples = 25 }],
  ['status aggregate mismatch', (data: any) => { data.status = 'partial' }],
  ['empty available', (data: any) => { data.layers.forEach((row: any) => Object.assign(row, { status: 'available', known_samples: 0, min_m3_m3: null, max_m3_m3: null })) }],
  ['out of range value', (data: any) => { data.layers[0].max_m3_m3 = 1.01 }],
])('fails closed for %s', async (_label, mutate) => {
  const data = valid(); mutate(data)
  const { root, app } = await mount(data)
  try {
    expect(root.querySelectorAll('.soil-water-layer')).toHaveLength(0)
    expect(root.textContent).toContain('Модельні дані про воду в ґрунті для обраної точки й дати не узгоджено.')
  } finally { app.unmount() }
})

it('rejects a non-ISO selected date even when payload and selected strings match', async () => {
  const data = valid(); data.date = '2026-02-30'
  const { root, app } = await mount(data, { tripDate: '2026-02-30' })
  try { expect(root.querySelectorAll('.soil-water-layer')).toHaveLength(0) } finally { app.unmount() }
})

it('keeps malformed or absent optional bindings unknown', async () => {
  const { root, app } = await mount(valid(), { selectedPoint: undefined, sourceDigest: undefined })
  try { expect(root.querySelectorAll('.soil-water-layer')).toHaveLength(0) } finally { app.unmount() }
})
