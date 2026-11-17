// @vitest-environment jsdom
import { createApp, nextTick } from 'vue'
import { expect, it } from 'vitest'
import SurfaceObservation from './SurfaceObservation.vue'

const point = { latitude: 59.985, longitude: 10.734 }
const observation = (override: Record<string, unknown> = {}) => ({
  status: 'available', basis: 'sentinel2_l2a_scl_point', assessment_date: '2026-10-26', requested_point: point,
  observed_at: '2026-10-25T10:35:00Z', retrieved_at: '2026-10-26T12:00:00Z', scene_age_days: 1,
  scene_id: 'native-scene-id', scl_class: 6, condition: 'water', resolution_m: 20,
  selection_scope: 'bounded_catalogue_result', ...override,
})

async function mount(data = observation(), tripDate = '2026-10-26') {
  const root = document.createElement('div'); const app = createApp(SurfaceObservation, { observation: data, selectedPoint: point, tripDate }); app.mount(root); await nextTick()
  return { root, app }
}

it('shows a bound native water class with UTC date age and resolution', async () => {
  const { root, app } = await mount()
  try {
    expect(root.querySelector('.surface-observation')?.classList).toContain('is-water')
    expect(root.textContent).toContain('2026-10-25 · UTC')
    expect(root.textContent).toContain('1 доба до дати поїздки')
    expect(root.textContent).toContain('Клас SCL 6 · вода')
    expect(root.textContent).toContain('Рідна комірка 20 м')
  } finally { app.unmount() }
})

it.each([
  ['cloud', observation({ status: 'partial', scl_class: 9, condition: 'cloud' }), 'Хмари'],
  ['snow', observation({ status: 'partial', scl_class: 11, condition: 'snow_ice' }), 'Сніг / лід'],
  ['nonwater', observation({ scl_class: 5, condition: 'not_vegetated' }), 'Без рослинності'],
])('renders $0 as its SCL condition without a dry or frozen claim', async (_name, data, label) => {
  const { root, app } = await mount(data)
  try {
    expect(root.textContent).toContain(label)
    expect(root.textContent).not.toMatch(/сух|промерз|затоплен/i)
  } finally { app.unmount() }
})

it.each([
  ['future observation', { observed_at: '2026-10-27T00:00:00Z', scene_age_days: -1 }],
  ['malformed timestamp', { observed_at: '2026-02-30T10:35:00Z' }],
  ['wrong condition for native class', { condition: 'vegetation' }],
  ['wrong selected point', { requested_point: { latitude: 59.986, longitude: 10.734 } }],
  ['invalid class', { scl_class: 12, condition: 'unknown' }],
])('keeps $0 unknown rather than presenting a stale surface', async (_name, override) => {
  const { root, app } = await mount(observation(override))
  try {
    expect(root.querySelector('.surface-observation')?.classList).toContain('is-unknown')
    expect(root.textContent).toContain('Немає узгодженого супутникового спостереження')
    expect(root.textContent).not.toContain('Клас SCL')
  } finally { app.unmount() }
})

it('shows a genuine same-day dated class without claiming current trip conditions', async () => {
  const data = observation({ observed_at: '2026-10-26T10:35:00Z', retrieved_at: '2026-10-26T12:00:00Z', scene_age_days: 0 })
  const { root, app } = await mount(data)
  try {
    expect(root.querySelector('.surface-observation')?.classList).toContain('is-water')
    expect(root.textContent).toContain('2026-10-26 · UTC')
    expect(root.textContent).toContain('0 діб до дати поїздки')
    expect(root.textContent).toContain('не оцінка проїзності чи стану поверхні на дату поїздки')
  } finally { app.unmount() }
})

it('accepts the real provider fractional UTC seconds without discarding the observed class', async () => {
  const { root, app } = await mount(observation({ observed_at: '2026-10-25T10:44:25.821000Z', retrieved_at: '2026-10-26T13:02:22.787285Z', status: 'partial', scl_class: 8, condition: 'cloud' }))
  try {
    expect(root.textContent).toContain('Клас SCL 8 · Хмари')
    expect(root.textContent).toContain('AWS Earth Search')
  } finally { app.unmount() }
})
