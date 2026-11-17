// @vitest-environment jsdom
import { createApp, nextTick } from 'vue'
import { expect, it, vi } from 'vitest'
const state = vi.hoisted(() => ({ map: null as any }))
vi.mock('./components/RouteMap.vue', () => ({ default: {
  props: ['sections', 'selectedSectionIndex', 'previewSectionIndex', 'inspectedSection', 'inspecting', 'routes'],
  emits: ['section', 'previewSection', 'route'],
  setup(props: any) { state.map = props },
  template: '<div><button data-map-action="pick" @click="$emit(\'section\', 1)">Map section 2</button><button data-map-action="hover" @mouseenter="$emit(\'previewSection\', 2)" @mouseleave="$emit(\'previewSection\', null)">Preview section 3</button><button data-map-action="open" @click="$emit(\'route\', \'transect-1\')">Open line</button></div>',
} }))
import RoutePlanner from './RoutePlanner.vue'
const flush = async () => { for (let i = 0; i < 4; i++) { await Promise.resolve(); await nextTick() } }
const planId = 'a'.repeat(32)
const sections = [0, 1, 2].map(index => ({ index, from_m: index * 700, to_m: (index + 1) * 700, point: { longitude: 10.73 + index * .005, latitude: 59.982 + index * .005 }, geometry: { type: 'LineString', coordinates: [[10.73 + index * .005, 59.982 + index * .005], [10.735 + index * .005, 59.987 + index * .005]] } }))
function fixtureClient() {
  let date = ''
  return { get: vi.fn(), post: vi.fn().mockImplementation((path, body) => {
    if (path === '/terrain-path-plans') { date = body.trip_date; return Promise.resolve({ request: body, plan_id: planId, analysis_kind: 'terrain_candidate', routes: [{ id: 'transect-1', name: 'Кандидат шляху', distance_m: 2100, geometry_kind: 'terrain_candidate', geometry: { type: 'LineString', coordinates: [[10.73, 59.982], [10.74, 59.995], [10.75, 60]] }, conditions: { status: 'not_assessed', summary_uk: 'Проїзд не підтверджено' } }], source: { id: 'terrain-search-grid' }, warnings_uk: [] }) }
    if (path === '/terrain-profile') return Promise.resolve({ plan_id: planId, route_id: 'transect-1', trip_date: date, status: 'available', synthetic: false, evidence_scope: 'spaced_point_samples', coverage: 'not_continuous', distance_m: 2100, sample_spacing_m: 210, points: Array.from({ length: 11 }, (_, index) => ({ chainage_m: index * 210, point: { longitude: 10.73, latitude: 59.982 }, elevation_m: 100, land_cover_class: 10, land_cover_label: 'tree_cover' })), sources: [], warnings_uk: [] })
    if (path === '/route-context') return Promise.resolve({ plan_id: planId, route_id: 'transect-1', trip_date: date, section_index: body.section_index, sections, land_cover: { class: 10, label: 'tree_cover', reference_year: 2021 }, terrain: { elevation_m: 100 + body.section_index }, sources: [], warnings_uk: [] })
    throw new Error(`Unexpected request: ${path}`)
  }) }
}
async function start(root: HTMLElement) { root.querySelector<HTMLButtonElement>('.reference-button')!.click(); await flush(); root.querySelector<HTMLButtonElement>('.plan-button')!.click(); await flush() }

it('connects an actual map-section event to the same plan inspector and reopens that selection', async () => {
  const client = fixtureClient(), root = document.createElement('div')
  const app = createApp(RoutePlanner, { client }); app.mount(root)
  try {
    await start(root)
    expect(state.map.sections).toEqual(sections)
    expect(state.map.selectedSectionIndex).toBe(0)
    root.querySelector<HTMLButtonElement>('[data-map-action="pick"]')!.click(); await flush()
    expect(client.post.mock.calls.filter(call => call[0] === '/route-context').map(call => call[1])).toEqual([0, 1].map(section_index => ({ plan_id: planId, route_id: 'transect-1', section_index })))
    expect(state.map.inspectedSection).toEqual(sections[1])
    expect(state.map.selectedSectionIndex).toBe(1)
    expect(root.querySelector('[data-section-index="1"]')?.getAttribute('aria-pressed')).toBe('true')
    root.querySelector<HTMLButtonElement>('[aria-label="Закрити деталі"]')!.click(); await flush()
    expect(state.map.inspecting).toBe(false)
    expect(state.map.inspectedSection).toBeNull()
    root.querySelector<HTMLButtonElement>('[data-map-action="open"]')!.click(); await flush()
    expect(client.post.mock.lastCall).toEqual(['/route-context', { plan_id: planId, route_id: 'transect-1', section_index: 1 }])
    expect(client.post.mock.calls.filter(call => call[0] === '/terrain-profile')).toHaveLength(1)
    expect(client.post.mock.calls.filter(call => call[0] === '/terrain-path-plans')).toHaveLength(1)
  } finally { app.unmount() }
})

it('selects a dynamically supplied fifth section through the planner and map', async () => {
  const client = fixtureClient(), original = client.post.getMockImplementation()!
  const dynamic = Array.from({ length: 5 }, (_, index) => ({ ...sections[0]!, index, from_m: index * 420, to_m: (index + 1) * 420, label_uk: `Місцевість ${index}` }))
  client.post.mockImplementation(async (path, body) => {
    const result = await original(path, body)
    return path === '/route-context' ? { ...result, sections: dynamic } : result
  })
  const root = document.createElement('div'), app = createApp(RoutePlanner, { client }); app.mount(root)
  try {
    await start(root)
    expect(root.querySelectorAll('[data-section-index]')).toHaveLength(5)
    root.querySelector<HTMLButtonElement>('[data-section-index="4"]')!.click(); await flush()
    expect(client.post.mock.calls.filter(call => call[0] === '/route-context').map(call => call[1].section_index)).toEqual([0, 4])
    expect(state.map.selectedSectionIndex).toBe(4)
    expect(state.map.inspectedSection).toEqual(dynamic[4])
    expect(root.querySelector('[data-section-index="4"]')?.getAttribute('aria-pressed')).toBe('true')
  } finally { app.unmount() }
})

it('previews map and keyboard focus without fetching or replacing loaded evidence', async () => {
  const client = fixtureClient(), root = document.createElement('div')
  const app = createApp(RoutePlanner, { client }); app.mount(root)
  try {
    await start(root)
    const calls = client.post.mock.calls.length
    root.querySelector('[data-map-action="hover"]')!.dispatchEvent(new Event('mouseenter')); await flush()
    expect(state.map.previewSectionIndex).toBe(2)
    expect(state.map.inspectedSection).toEqual(sections[0])
    root.querySelector('[data-map-action="hover"]')!.dispatchEvent(new Event('mouseleave')); await flush()
    expect(state.map.previewSectionIndex).toBeNull()
    root.querySelector('[data-section-index="1"]')!.dispatchEvent(new Event('focus')); await flush()
    expect(state.map.previewSectionIndex).toBe(1)
    expect(client.post).toHaveBeenCalledTimes(calls)
    root.querySelector<HTMLButtonElement>('[data-map-action="pick"]')!.click(); await flush()
    expect(state.map.previewSectionIndex).toBeNull()
    expect(state.map.inspectedSection).toEqual(sections[1])
  } finally { app.unmount() }
})

it('clears spatial evidence on date edits and cannot restore it from a pending section reply', async () => {
  let resolve!: (value: unknown) => void
  const client = fixtureClient(), original = client.post.getMockImplementation()!
  client.post.mockImplementation((path, body) => path === '/route-context' && body.section_index === 1 ? new Promise(value => { resolve = value }) : original(path, body))
  const root = document.createElement('div'), app = createApp(RoutePlanner, { client }); app.mount(root)
  try {
    await start(root)
    const date = root.querySelector<HTMLInputElement>('input[type=date]')!, oldDate = date.value
    root.querySelector<HTMLButtonElement>('[data-map-action="pick"]')!.click(); await flush()
    expect(state.map.inspectedSection).toBeNull()
    expect(state.map.sections).toEqual(sections)
    date.value = '2026-12-20'; date.dispatchEvent(new Event('input', { bubbles: true })); await flush()
    expect(state.map.sections).toEqual([])
    expect(state.map.previewSectionIndex).toBeNull()
    expect(state.map.selectedSectionIndex).toBe(0)
    resolve({ plan_id: planId, route_id: 'transect-1', trip_date: oldDate, section_index: 1, sections, sources: [], warnings_uk: [] }); await flush()
    expect(state.map.sections).toEqual([])
    expect(state.map.inspectedSection).toBeNull()
    expect(state.map.routes).toEqual([])
    expect(root.querySelector('.route-drawer')).toBeNull()
    expect(root.querySelector<HTMLButtonElement>('.plan-button')!.disabled).toBe(false)
  } finally { app.unmount() }
})

it('leaves inspection when opening the mobile trip editor and preserves the selected trip', async () => {
  const client = fixtureClient(), root = document.createElement('div')
  const app = createApp(RoutePlanner, { client }); app.mount(root)
  try {
    await start(root)
    root.querySelector<HTMLButtonElement>('[data-map-action="pick"]')!.click(); await flush()
    const calls = client.post.mock.calls.length
    root.querySelector<HTMLButtonElement>('.edit-trip')!.click(); await flush()
    expect(root.querySelector('.route-sidebar')?.classList.contains('editing-trip')).toBe(true)
    expect(state.map.inspecting).toBe(false)
    expect(root.querySelector('.route-drawer')).toBeNull()
    expect(state.map.selectedSectionIndex).toBe(1)
    expect(root.querySelector<HTMLInputElement>('input[type=number]')!.value).toBe('20')
    expect(client.post).toHaveBeenCalledTimes(calls)
  } finally { app.unmount() }
})
