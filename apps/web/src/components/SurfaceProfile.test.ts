// @vitest-environment jsdom
import { createApp, nextTick } from 'vue'
import { expect, it, vi } from 'vitest'
import SurfaceProfile from './SurfaceProfile.vue'

const points = [
  { chainage_m: 0, point: { longitude: 10.73, latitude: 59.982 } },
  { chainage_m: 250, point: { longitude: 10.732, latitude: 59.983 } },
]
const sourceDigest = `sha256:${'a'.repeat(64)}`
const summary = (override: Record<string, unknown> = {}) => ({
  status: 'partial', basis: 'sentinel2_l2a_scl_profile_points', coverage: 'discrete_points', assessment_date: '2026-10-26',
  retrieved_at: '2026-10-26T12:00:00Z', observed_at: '2026-10-25T10:35:00Z', scene_id: 'S2C_32VNM_20261025_0_L2A',
  scene_age_days: 1, resolution_m: 20, selection_scope: 'bounded_catalogue_result', source_content_sha256: sourceDigest,
  samples: [
    { chainage_m: 0, requested_point: points[0].point, scl_class: 6, condition: 'water', status: 'available' },
    { chainage_m: 250, requested_point: points[1].point, scl_class: 9, condition: 'cloud', status: 'partial' },
  ], ...override,
})
const source = (override: Record<string, unknown> = {}) => ({
  id: 'sentinel-2-l2a', status: 'partial', extraction_scope: 'spaced_scene_classification_points',
  retrieved_at: '2026-10-26T12:00:00Z', observed_at: '2026-10-25T10:35:00Z', content_sha256: sourceDigest,
  data: { extraction_scope: 'spaced_scene_classification_points', assessment_date: '2026-10-26', scene_id: 'S2C_32VNM_20261025_0_L2A', samples: summary().samples }, ...override,
})

async function mount(data: unknown = summary(), sourceData: unknown = source(), ready = true) {
  const root = document.createElement('div'), inspect = vi.fn()
  const app = createApp(SurfaceProfile, { summary: data, source: sourceData, profilePoints: points, tripDate: '2026-10-26', inspectionReady: ready, onInspectPoint: inspect })
  app.mount(root); await nextTick()
  return { root, app, inspect }
}

it('keeps the disclosure closed without requests and exposes valid dated classes only when opened', async () => {
  const { root, app, inspect } = await mount()
  try {
    const disclosure = root.querySelector('details')!
    expect(disclosure.open).toBe(false)
    expect(root.textContent).toContain('2026-10-25')
    expect(root.textContent).toContain('2 точки')
    expect(root.querySelectorAll('[data-testid="surface-sample"]')).toHaveLength(2)
    disclosure.open = true; disclosure.dispatchEvent(new Event('toggle')); await nextTick()
    expect(root.textContent).toContain('Клас води')
    expect(root.textContent).toContain('Хмари')
    expect(root.textContent).toContain('20 м')
    expect(root.textContent).toMatch(/не коридор/i)
    expect(root.textContent).toMatch(/не прогноз/i)
    const button = root.querySelector<HTMLButtonElement>('[aria-label*="0 м"]')!
    button.click()
    expect(inspect).toHaveBeenCalledWith(0)
  } finally { app.unmount() }
})

it.each([
  ['wrong source digest', () => source({ content_sha256: 'sha256:short' })],
  ['summary digest that differs from its source', () => summary({ source_content_sha256: `sha256:${'b'.repeat(64)}` })],
  ['wrong source scene', () => source({ data: { ...source().data, scene_id: 'foreign' } })],
  ['wrong observed timestamp', () => source({ observed_at: '2026-10-25T10:36:00Z' })],
  ['sample point mismatch', () => summary({ samples: [{ ...summary().samples[0], requested_point: { longitude: 0, latitude: 0 } }, summary().samples[1]] })],
  ['class condition mismatch', () => summary({ samples: [{ ...summary().samples[0], condition: 'vegetation' }, summary().samples[1]] })],
  ['future scene', () => summary({ observed_at: '2026-10-27T00:00:00Z', scene_age_days: -1 })],
])('fails closed for %s while retaining the native disclosure', async (_name, corrupt) => {
  const { root, app } = await mount(corrupt())
  try {
    expect(root.querySelector('details')?.open).toBe(false)
    expect(root.textContent).toContain('Дані супутника не узгоджено')
    expect(root.textContent).not.toContain('Клас води')
  } finally { app.unmount() }
})

it('does not enable selection without a trusted saved geometry binding', async () => {
  const { root, app } = await mount(summary(), source(), false)
  try {
    root.querySelector('details')!.open = true; root.querySelector('details')!.dispatchEvent(new Event('toggle')); await nextTick()
    expect(root.querySelectorAll('[data-testid="surface-inspect"]')).toHaveLength(0)
  } finally { app.unmount() }
})

it('rejects a self-consistent summary and source from another assessment date', async () => {
  const data = summary({ assessment_date: '2026-10-27', scene_age_days: 2 })
  const src = source({ data: { ...source().data, assessment_date: '2026-10-27' } })
  const { root, app } = await mount(data, src)
  try { expect(root.querySelectorAll('[data-testid="surface-sample"]')).toHaveLength(0) }
  finally { app.unmount() }
})

it.each([
  ['invalid calendar date', summary({ assessment_date: '2026-99-26' }), source()],
  ['null source sample', summary(), source({ data: { ...source().data, samples: [null, summary().samples[1]] } })],
])('keeps malformed %s local instead of throwing during profile rendering', async (_name, data, src) => {
  const { root, app } = await mount(data, src)
  try {
    expect(root.textContent).toContain('Дані супутника не узгоджено')
    expect(root.querySelectorAll('[data-testid="surface-inspect"]')).toHaveLength(0)
  } finally { app.unmount() }
})
