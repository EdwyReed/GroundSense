// @vitest-environment jsdom
import { createApp, nextTick } from 'vue'
import { expect, it } from 'vitest'
import WeatherDayConditions from './WeatherDayConditions.vue'
import type { WeatherDaySummary } from '../lib/weatherDayTypes'

const fixture = (): WeatherDaySummary => ({
  date: '2026-10-26', timezone: 'UTC', basis: 'weather_model_not_field_observation', status: 'available',
  precipitation: { status: 'available', total_mm: 0, known_intervals: 24, expected_intervals: 24 },
  soil_temperature: { status: 'available', min_c: -2, max_c: 3, known_samples: 24, expected_samples: 24, at_or_below_zero_samples: 4 },
  snow_depth: { status: 'available', min_m: .02, max_m: .05, known_samples: 24, expected_samples: 24 },
})

it('shows selected-day model rain, surface temperature and snow with their native support limits', async () => {
  const root = document.createElement('div'); const app = createApp(WeatherDayConditions, { summary: fixture(), tripDate: '2026-10-26' }); app.mount(root)
  try {
    await nextTick()
    expect(root.textContent).toContain('2026-10-26 · UTC')
    expect(root.querySelector('.day-precipitation')?.textContent).toContain('0,0 мм')
    expect(root.querySelector('.day-precipitation')?.textContent).toContain('24 / 24')
    expect(root.querySelector('.day-soil-temperature')?.textContent).toContain('-2,0–3,0 °C')
    expect(root.querySelector('.day-snow')?.textContent).toContain('2,0–5,0 см')
    expect(root.textContent).toContain('4 / 24 точок ≤ 0 °C')
    expect(root.textContent).toContain('не підтверджують промерзання')
    expect(root.textContent).not.toContain('Проїзд дозволено')
  } finally { app.unmount() }
})

it.each([{ date: '2026-10-27' }, { timezone: 'local' }, { basis: 'field_measurement' }])('hides numbers whose date or model basis is mismatched: %o', async override => {
  const root = document.createElement('div'); const app = createApp(WeatherDayConditions, { summary: { ...fixture(), ...override } as WeatherDaySummary, tripDate: '2026-10-26' }); app.mount(root)
  try {
    await nextTick()
    expect(root.querySelector('.day-precipitation')).toBeNull()
    expect(root.textContent).toContain('Немає узгоджених даних')
  } finally { app.unmount() }
})

it('never labels incomplete accumulation as a daily zero and marks partial sample ranges', async () => {
  const summary = fixture()
  summary.precipitation = { ...summary.precipitation, status: 'partial', known_intervals: 23, total_mm: 0 }
  summary.soil_temperature = { ...summary.soil_temperature, status: 'partial', known_samples: 18 }
  const root = document.createElement('div'); const app = createApp(WeatherDayConditions, { summary, tripDate: '2026-10-26' }); app.mount(root)
  try {
    await nextTick()
    expect(root.querySelector('.day-precipitation dd')?.textContent).toBe('— мм')
    expect(root.querySelector('.day-precipitation small')?.textContent).toContain('23 / 24')
    expect(root.querySelector('.day-soil-temperature')?.textContent).toContain('Неповна вибірка')
  } finally { app.unmount() }
})

it.each([null, -1, Number.NaN, Number.POSITIVE_INFINITY])('keeps invalid or absent snow unknown instead of a dry-ground claim: %s', async value => {
  const summary = fixture(); summary.snow_depth.min_m = value
  const root = document.createElement('div'); const app = createApp(WeatherDayConditions, { summary, tripDate: '2026-10-26' }); app.mount(root)
  try {
    await nextTick()
    expect(root.querySelector('.day-snow dd')?.textContent).toBe('— см')
  } finally { app.unmount() }
})
