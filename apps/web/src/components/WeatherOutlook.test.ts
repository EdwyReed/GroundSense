// @vitest-environment jsdom
import { createApp, nextTick } from 'vue'
import { expect, it } from 'vitest'
import WeatherOutlook from './WeatherOutlook.vue'
import type { WeatherOutlookData } from '../lib/weatherOutlookTypes'

const day = (date: string): WeatherOutlookData['days'][number] => ({
  date, timezone: 'UTC', basis: 'weather_model_not_field_observation', status: 'available',
  precipitation: { status: 'available', total_mm: 1.5, known_intervals: 24, expected_intervals: 24 },
  soil_temperature: { status: 'available', min_c: -1, max_c: 3, known_samples: 24, expected_samples: 24, at_or_below_zero_samples: 5 },
  snow_depth: { status: 'available', min_m: .01, max_m: .04, known_samples: 24, expected_samples: 24 },
})
const fixture = (): WeatherOutlookData => ({
  date: '2026-10-26', timezone: 'UTC', basis: 'weather_model_not_field_observation', horizon_days: 2, status: 'available',
  days: [day('2026-10-27'), day('2026-10-28')],
})

function mount(outlook: WeatherOutlookData | null | undefined, tripDate = '2026-10-26') {
  const root = document.createElement('div'); const app = createApp(WeatherOutlook, { outlook, tripDate }); app.mount(root)
  return { root, app }
}

it('renders two ordered model days in a closed native disclosure without a passability prediction', async () => {
  const { root, app } = mount(fixture())
  try {
    await nextTick()
    const details = root.querySelector('details.weather-outlook') as HTMLDetailsElement
    expect(details.open).toBe(false)
    expect(details.querySelector('summary')?.textContent).toBe('Наступні 2 дні · погода')
    expect(root.querySelectorAll('.outlook-day')).toHaveLength(2)
    expect(root.querySelector('.outlook-day')?.getAttribute('data-date')).toBe('2026-10-27')
    expect(root.querySelector('.outlook-rain')?.textContent).toContain('1,5 мм')
    expect(root.querySelector('.outlook-soil')?.textContent).toContain('-1,0–3,0 °C')
    expect(root.querySelector('.outlook-snow')?.textContent).toContain('1,0–4,0 см')
    expect(root.textContent).toContain('не є оцінкою висихання чи проїзності')
    expect(root.textContent).toContain('не означають сухий ґрунт')
    expect(root.textContent).not.toMatch(/проїзд (можлив|дозволен)|passability/i)
  } finally { app.unmount() }
})

it.each([
  ['malformed ISO trip date', fixture(), '2026-02-30'],
  ['mismatched binding', { ...fixture(), date: '2026-10-25' }, '2026-10-26'],
  ['wrong timezone', { ...fixture(), timezone: 'Europe/Kyiv' }, '2026-10-26'],
  ['wrong basis', { ...fixture(), basis: 'field_measurement' }, '2026-10-26'],
  ['wrong horizon', { ...fixture(), horizon_days: 3 }, '2026-10-26'],
  ['unexpected status', { ...fixture(), status: 'complete' }, '2026-10-26'],
  ['mismatched ordered day', { ...fixture(), days: [day('2026-10-28')] }, '2026-10-26'],
])('shows unknown for %s outer binding', async (_, outlook, tripDate) => {
  const { root, app } = mount(outlook as WeatherOutlookData, tripDate)
  try { await nextTick(); expect(root.textContent).toContain('Немає узгоджених даних'); expect(root.querySelector('.outlook-day')).toBeNull() } finally { app.unmount() }
})

it('accepts a one-day partial horizon only as the exact next-day prefix', async () => {
  const outlook = fixture(); outlook.status = 'partial'; outlook.days = [day('2026-10-27')]
  const { root, app } = mount(outlook)
  try { await nextTick(); expect(root.querySelectorAll('.outlook-day')).toHaveLength(1); expect(root.textContent).toContain('Горизонт моделі може бути коротшим') } finally { app.unmount() }
})

it('binds the two-day prefix across a UTC year boundary', async () => {
  const outlook = fixture(); outlook.date = '2026-12-31'; outlook.days = [day('2027-01-01'), day('2027-01-02')]
  const { root, app } = mount(outlook, '2026-12-31')
  try { await nextTick(); expect(root.querySelectorAll('.outlook-day')).toHaveLength(2); expect(root.querySelectorAll('.outlook-day')[1]?.getAttribute('data-date')).toBe('2027-01-02') } finally { app.unmount() }
})

it('never turns 23 of 24 rain intervals or a null total into a partial daily sum', async () => {
  const outlook = fixture(); outlook.status = 'partial'; outlook.days[1].status = 'partial'; outlook.days[1].precipitation = { status: 'partial', total_mm: null, known_intervals: 23, expected_intervals: 24 }
  const { root, app } = mount(outlook)
  try { await nextTick(); const rain = root.querySelectorAll('.outlook-rain')[1]; expect(rain?.textContent).toContain('— мм'); expect(rain?.textContent).toContain('23 / 24'); expect(rain?.textContent).toContain('Повну добову суму не отримано') } finally { app.unmount() }
})

it('renders a valid partial instantaneous range with its coverage count', async () => {
  const outlook = fixture(); outlook.status = 'partial'; outlook.days[1].status = 'partial'; outlook.days[1].soil_temperature = { ...outlook.days[1].soil_temperature, status: 'partial', known_samples: 12 }
  const { root, app } = mount(outlook)
  try { await nextTick(); const soil = root.querySelectorAll('.outlook-soil')[1]; expect(soil?.textContent).toContain('-1,0–3,0 °C'); expect(soil?.textContent).toContain('12 / 24'); expect(soil?.textContent).toContain('Неповна вибірка') } finally { app.unmount() }
})

it.each([Number.NaN, Number.POSITIVE_INFINITY, '1.5'])('withholds non-finite or non-numeric metric values without hiding independent metrics: %s', async value => {
  const outlook = fixture(); outlook.status = 'partial'; outlook.days[0].status = 'partial'; outlook.days[0].precipitation = { ...outlook.days[0].precipitation, total_mm: value as number }
  const { root, app } = mount(outlook)
  try { await nextTick(); expect(root.querySelector('.outlook-rain')?.textContent).toContain('— мм'); expect(root.querySelector('.outlook-soil')?.textContent).toContain('-1,0–3,0 °C'); expect(root.textContent).not.toContain('NaN'); expect(root.textContent).not.toContain('Infinity') } finally { app.unmount() }
})

it('withholds metrics with invalid counts or bounds while retaining another valid metric', async () => {
  const outlook = fixture(); outlook.status = 'partial'; outlook.days[0].status = 'partial'
  outlook.days[0].soil_temperature = { ...outlook.days[0].soil_temperature, known_samples: 25 }
  outlook.days[0].snow_depth = { ...outlook.days[0].snow_depth, min_m: -1 }
  const { root, app } = mount(outlook)
  try { await nextTick(); expect(root.querySelector('.outlook-soil')?.textContent).toContain('— °C'); expect(root.querySelector('.outlook-snow')?.textContent).toContain('— см'); expect(root.querySelector('.outlook-rain')?.textContent).toContain('1,5 мм') } finally { app.unmount() }
})

it('withholds a finite snow value that overflows during centimetre conversion', async () => {
  const outlook = fixture(); outlook.days[0].snow_depth.max_m = Number.MAX_VALUE
  const { root, app } = mount(outlook)
  try { await nextTick(); expect(root.querySelector('.outlook-snow')?.textContent).toContain('— см'); expect(root.textContent).not.toContain('Infinity'); expect(root.querySelector('.outlook-rain')?.textContent).toContain('1,5 мм') } finally { app.unmount() }
})

it('preserves coverage when all rain intervals exist but their sum is unavailable', async () => {
  const outlook = fixture(); outlook.status = 'partial'; outlook.days[0].status = 'partial'; outlook.days[0].precipitation = { status: 'partial', total_mm: null, known_intervals: 24, expected_intervals: 24 }
  const { root, app } = mount(outlook)
  try { await nextTick(); const rain = root.querySelector('.outlook-rain'); expect(rain?.textContent).toContain('— мм'); expect(rain?.textContent).toContain('24 / 24'); expect(rain?.textContent).toContain('Повну добову суму не отримано') } finally { app.unmount() }
})

it.each([
  ['available empty prefix', { ...fixture(), days: [] }],
  ['available one-day prefix', { ...fixture(), days: [day('2026-10-27')] }],
  ['available with a partial day', { ...fixture(), days: [day('2026-10-27'), { ...day('2026-10-28'), status: 'partial' }] }],
  ['partial with two available days', { ...fixture(), status: 'partial' }],
  ['unavailable with available days', { ...fixture(), status: 'unavailable' }],
  ['partial empty prefix', { ...fixture(), status: 'partial', days: [] }],
])('withholds the whole outlook for contradictory aggregate status: %s', async (_, outlook) => {
  const { root, app } = mount(outlook as WeatherOutlookData)
  try { await nextTick(); expect(root.querySelector('.weather-outlook')).toBeNull(); expect(root.querySelector('.outlook-day')).toBeNull(); expect(root.textContent).toContain('Немає узгоджених даних') } finally { app.unmount() }
})

it('shows unknown rather than an empty disclosure for a valid unavailable empty prefix', async () => {
  const { root, app } = mount({ ...fixture(), status: 'unavailable', days: [] })
  try { await nextTick(); expect(root.querySelector('.weather-outlook')).toBeNull(); expect(root.textContent).toContain('Немає узгоджених даних') } finally { app.unmount() }
})
