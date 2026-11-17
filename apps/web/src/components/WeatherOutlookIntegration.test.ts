// @vitest-environment jsdom
import { createApp, h, nextTick, reactive } from 'vue'
import { expect, it, vi } from 'vitest'
import WeatherDayConditions from './WeatherDayConditions.vue'
import SectionContext from './SectionContext.vue'
import type { WeatherDaySummary } from '../lib/weatherDayTypes'

const day = (date: string, rain = 2.1): WeatherDaySummary => ({ date, timezone: 'UTC', basis: 'weather_model_not_field_observation', status: 'available',
  precipitation: { status: 'available', total_mm: rain, known_intervals: 24, expected_intervals: 24 },
  soil_temperature: { status: 'available', min_c: 4, max_c: 9, known_samples: 24, expected_samples: 24, at_or_below_zero_samples: 0 },
  snow_depth: { status: 'available', min_m: 0, max_m: 0, known_samples: 24, expected_samples: 24 } })
const outlook = () => ({ date: '2026-10-26', timezone: 'UTC' as const, basis: 'weather_model_not_field_observation' as const, horizon_days: 2 as const, status: 'available' as const, days: [day('2026-10-27', 14.7), day('2026-10-28', 0)] })
const flush = async () => { await Promise.resolve(); await nextTick() }

it('embeds exactly one initially closed local outlook after the current-day weather', async () => {
  const root = document.createElement('div'), app = createApp(WeatherDayConditions, { summary: day('2026-10-26'), tripDate: '2026-10-26', outlook: outlook() }); app.mount(root)
  try {
    await nextTick()
    const future = root.querySelector<HTMLDetailsElement>('.weather-outlook')
    expect(future?.open).toBe(false)
    expect(root.querySelectorAll('.weather-outlook')).toHaveLength(1)
    expect(future?.textContent).toContain('14,7 мм')
    expect(root.querySelector('.day-precipitation')?.textContent).toContain('2,1 мм')
    expect(root.querySelector('.weather-day-metrics')!.compareDocumentPosition(future!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    future!.querySelector('summary')!.click(); await nextTick()
    expect(future!.open).toBe(true)
  } finally { app.unmount() }
})

it('withdraws old outlook values even if a new current-day summary has already arrived', async () => {
  const props = reactive({ summary: day('2026-10-26'), tripDate: '2026-10-26', outlook: outlook() })
  const root = document.createElement('div'), app = createApp({ render: () => h(WeatherDayConditions, props) }); app.mount(root)
  try {
    await nextTick()
    expect(root.textContent).toContain('14,7 мм')
    props.tripDate = '2026-10-27'; props.summary = day('2026-10-27', 9.9); await nextTick()
    expect(root.textContent).not.toContain('14,7 мм')
    expect(root.querySelector('.day-precipitation')?.textContent).toContain('9,9 мм')
  } finally { app.unmount() }
})

const planId = 'a'.repeat(32)
function context(index = 0) {
  return { plan_id: planId, route_id: 'transect-1', trip_date: '2026-10-26', section_index: index, status: 'partial', synthetic: false, evidence_scope: 'point_sample', coverage: 'not_continuous',
    sections: [0, 1, 2].map(index => ({ index, from_m: index * 1000, to_m: (index + 1) * 1000, point: { latitude: 59.98 + index / 1000, longitude: 10.73 }, geometry: { type: 'LineString', coordinates: [[10.73, 59.98], [10.75, 60]] } })),
    weather: { assessment_date: '2026-10-26', status: 'available', day_summary: day('2026-10-26'), outlook: outlook() }, sources: [], warnings_uk: [] }
}

it('wires the off-road context outlook without a second API call and clears it during section reload', async () => {
  let resolve!: (value: unknown) => void
  const client = { get: vi.fn(), post: vi.fn().mockResolvedValueOnce(context()).mockImplementationOnce(() => new Promise(value => { resolve = value })) }
  const root = document.createElement('div'), app = createApp(SectionContext, { client, planId, routeId: 'transect-1', tripDate: '2026-10-26', analysisKind: 'terrain_transect' }); app.mount(root)
  try {
    await flush()
    expect(root.querySelectorAll('.weather-outlook')).toHaveLength(1)
    expect(root.textContent).toContain('14,7 мм')
    expect(client.post).toHaveBeenCalledOnce()
    root.querySelector<HTMLButtonElement>('.section-option[data-section-index="1"]')!.click(); await flush()
    expect(root.querySelector('.weather-outlook')).toBeNull()
    expect(root.textContent).not.toContain('14,7 мм')
    resolve(context(1)); await flush()
    expect(root.querySelectorAll('.weather-outlook')).toHaveLength(1)
    expect(client.post).toHaveBeenCalledTimes(2)
  } finally { app.unmount() }
})

it('does not render an outlook in the legacy road inspector even if an unexpected field is supplied', async () => {
  const client = { get: vi.fn(), post: vi.fn().mockResolvedValue(context()) }
  const root = document.createElement('div'), app = createApp(SectionContext, { client, planId, routeId: 'transect-1', tripDate: '2026-10-26' }); app.mount(root)
  try {
    await flush()
    expect(root.querySelector('.weather-outlook')).toBeNull()
    expect(root.querySelector('.day-precipitation')?.textContent).toContain('2,1 мм')
  } finally { app.unmount() }
})
