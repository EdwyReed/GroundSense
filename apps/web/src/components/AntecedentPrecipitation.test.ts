// @vitest-environment jsdom
import { createApp, nextTick } from 'vue'
import { expect, it } from 'vitest'
import AntecedentPrecipitation from './AntecedentPrecipitation.vue'
import type { AntecedentPrecipitationSummary } from '../lib/antecedentPrecipitationTypes'

const days = (total = 1): AntecedentPrecipitationSummary['days'] => Array.from({ length: 7 }, (_, index) => ({
  date: `2026-10-${String(19 + index).padStart(2, '0')}`,
  status: 'available', total_mm: total, known_intervals: 24, expected_intervals: 24,
}))
const fixture = (): AntecedentPrecipitationSummary => ({
  date: '2026-10-26', timezone: 'UTC', basis: 'weather_model_not_field_observation',
  window_start: '2026-10-19', window_end_exclusive: '2026-10-26', window_days: 7,
  status: 'available', total_mm: 7, known_intervals: 168, expected_intervals: 168, days: days(),
})

function mount(summary: AntecedentPrecipitationSummary, tripDate = '2026-10-26') {
  const root = document.createElement('div'); const app = createApp(AntecedentPrecipitation, { summary, tripDate }); app.mount(root)
  return { root, app }
}

it('renders a complete seven-day UTC model total and keeps daily sums collapsed', async () => {
  const { root, app } = mount(fixture())
  try {
    await nextTick()
    expect(root.textContent).toContain('Опади до поїздки')
    expect(root.textContent).toContain('7,0 мм')
    expect(root.textContent).toContain('168 / 168 інтервалів')
    expect(root.textContent).toContain('2026-10-19 — 2026-10-25 · UTC')
    const details = root.querySelector('details')!
    expect(details.open).toBe(false)
    expect(details.querySelectorAll('li')).toHaveLength(7)
    expect(root.textContent).toContain('не є виміряною вологістю ґрунту чи проїзністю')
  } finally { app.unmount() }
})

it('withholds a weekly total for 167 intervals while preserving valid daily totals', async () => {
  const summary = fixture(); summary.status = 'partial'; summary.total_mm = null; summary.known_intervals = 167
  summary.days[6] = { ...summary.days[6], status: 'partial', total_mm: null, known_intervals: 23 }
  const { root, app } = mount(summary)
  try {
    await nextTick()
    expect(root.querySelector('.antecedent-total')?.textContent).toBe('— мм')
    expect(root.textContent).toContain('167 / 168 інтервалів')
    expect(root.querySelector('details')?.textContent).toContain('2026-10-19: 1,0 мм · 24 / 24')
    expect(root.querySelector('details')?.textContent).toContain('2026-10-25: — мм · 23 / 24')
  } finally { app.unmount() }
})

it.each([
  ['numeric string', { total_mm: '7' }],
  ['malformed window', { window_start: '2026-10-20' }],
  ['false complete count', { known_intervals: 168, days: [...days(), { ...days()[6], known_intervals: 23 }] }],
])('shows unknown for %s summary', async (_, override) => {
  const { root, app } = mount({ ...fixture(), ...override } as AntecedentPrecipitationSummary)
  try { await nextTick(); expect(root.textContent).toContain('Немає узгоджених даних'); expect(root.textContent).not.toContain('7,0 мм') } finally { app.unmount() }
})

it('hides stale data after trip-date changes without any request', async () => {
  const { root, app } = mount(fixture(), '2026-10-27')
  try { await nextTick(); expect(root.textContent).toContain('Немає узгоджених даних'); expect(root.textContent).not.toContain('7,0 мм') } finally { app.unmount() }
})

it('retains good daily rows when complete interval values have an overflowed daily or weekly sum', async () => {
  const summary = fixture()
  summary.status = 'partial'; summary.total_mm = null
  summary.days[0] = { ...summary.days[0], status: 'partial', total_mm: null }
  const { root, app } = mount(summary)
  try {
    await nextTick()
    expect(root.querySelector('.antecedent-total')?.textContent).toBe('— мм')
    expect(root.textContent).toContain('168 / 168 інтервалів')
    expect(root.querySelectorAll('li')).toHaveLength(7)
    expect(root.querySelector('details')?.textContent).toContain('2026-10-20: 1,0 мм · 24 / 24')
  } finally { app.unmount() }
})

it('rejects a claimed complete weekly total when a complete-count day has no total', async () => {
  const summary = fixture()
  summary.days[0] = { ...summary.days[0], status: 'partial', total_mm: null }
  summary.total_mm = 6
  const { root, app } = mount(summary)
  try {
    await nextTick()
    expect(root.querySelector('.antecedent-total')).toBeNull()
    expect(root.textContent).toContain('Немає узгоджених даних')
  } finally { app.unmount() }
})
