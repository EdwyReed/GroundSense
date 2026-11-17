// @vitest-environment jsdom
import { createApp } from 'vue'
import { afterEach, expect, it, vi } from 'vitest'
import App from './App.vue'
vi.mock('./components/SchematicMap.vue', () => ({ default: { template: '<div>Карта</div>' } }))
vi.mock('./components/ForecastChart.vue', () => ({ default: { template: '<div>Графік постачальника</div>' } }))

afterEach(() => vi.unstubAllGlobals())

it('shows the matching live research calculation in the map inspector and forecast without changing stored road condition', async () => {
  const research = {
    status: 'research_only', model_version: 'live-warm-water/1', condition: 'less_adverse', summary_uk: 'Баланс від’ємний.', reason_codes: [],
    metrics: { precipitation_mm: 1, et0_mm: 4, net_atmospheric_input_mm: -3, horizon_hours: 48, max_mass_residual_mm: 0.001 },
    scenarios: [], drying_window: { kind: 'not_reached', earliest: null, latest: null, persistence_hours: 12, censored_scenarios: 3 }, assumptions_uk: [], source_refs: [],
  }
  vi.stubGlobal('fetch', vi.fn(async (input: any) => {
    const path = typeof input === 'string' ? input : input.url
    if (path === '/api/v1/bootstrap') return new Response(JSON.stringify({ workspace: { mode: 'public_data' }, assets: [{ id: 'GS-1', name: 'Точка', type: 'site', condition: 'unknown', reason: 'Немає огляду' }], segments: [], sources: [], features: [], models: [], observations: [], inspections: [], context: { assessment_date: '2026-10-25', gross_mass_t: 20 }, user: { role: 'engineer' }, csrf_token: 'test', map: {} }), { status: 200 })
    if (path.includes('/forecast?')) return new Response(JSON.stringify({ asset_id: 'GS-1', assessment_date: '2026-10-25', gross_mass_t: 20, series: [], research }), { status: 200 })
    return new Response('{}', { status: 200 })
  }))
  const root = document.createElement('div'); document.body.append(root)
  const app = createApp(App); app.config.errorHandler = () => {}; app.mount(root)
  try {
    await vi.waitFor(() => expect(root.textContent).toContain('Дослідницький водний баланс'), { timeout: 3000 })
    expect(root.textContent).toContain('Проїзд не оцінено')
    ;[...root.querySelectorAll<HTMLButtonElement>('.masthead nav button')].find(button => button.textContent === 'Прогноз')?.click()
    await vi.waitFor(() => expect(root.textContent).toContain('Баланс від’ємний.'))
    expect(root.textContent).toContain('Графік постачальника')
    expect(root.querySelector('.forecast .panel')?.firstElementChild?.getAttribute('data-testid')).toBe('research-assessment')
    const date = root.querySelector<HTMLInputElement>('.querybar input[type="date"]')!
    date.value = '2026-10-26'; date.dispatchEvent(new Event('input', { bubbles: true }))
    await vi.waitFor(() => expect(root.textContent).not.toContain('Баланс від’ємний.'))
  } finally { app.unmount(); root.remove() }
})
