// @vitest-environment jsdom
import { createApp, nextTick } from 'vue'
import { expect, it, vi } from 'vitest'
import { segmentLength } from './lib/transectSelection'
const state = vi.hoisted(() => ({ map: null as any }))
vi.mock('./components/RouteMap.vue', () => ({ default: {
  props: ['sections', 'selectedSectionIndex', 'inspectionPoint', 'inspectedSection', 'routes'],
  emits: ['lineChainage', 'section'],
  setup(props: any) { state.map = props },
  template: '<div><button data-pick="250" @click="$emit(\'lineChainage\', 250)">Pick 250m</button><button data-pick="260" @click="$emit(\'lineChainage\', 260)">Pick 260m</button><button data-pick="midpoint" @click="$emit(\'section\', 2)">Section midpoint</button></div>',
} }))
import RoutePlanner from './RoutePlanner.vue'
const planId = 'b'.repeat(32)
const coordinates: [number, number][] = [[10, 59], [10, 59.003]]
const total = segmentLength(coordinates[0], coordinates[1])
const point = (metres: number) => ({ longitude: 10, latitude: 59 + .003 * metres / total })
const sections = [0, 1, 2].map(index => ({ index, from_m: total * index / 3, to_m: total * (index + 1) / 3, point: point(total * (index + .5) / 3), geometry: { type: 'LineString', coordinates: [[10, 59 + index * .001], [10, 59 + (index + 1) * .001]] } }))
const flush = async () => { for (let i = 0; i < 5; i++) { await Promise.resolve(); await nextTick() } }
function fixtureClient(change: (context: any, body: any) => any = context => context, analysisKind: 'terrain_candidate' | 'terrain_transect' = 'terrain_candidate') {
  let date = ''
  return { get: vi.fn(), post: vi.fn().mockImplementation((path, body) => {
    if (path === '/terrain-path-plans') { date = body.trip_date; return Promise.resolve({ request: body, plan_id: planId, analysis_kind: analysisKind, routes: [{ id: 'transect-1', name: 'Кандидат', distance_m: total, geometry_kind: analysisKind === 'terrain_candidate' ? 'terrain_candidate' : 'analysis_transect', geometry: { type: 'LineString', coordinates }, conditions: { status: 'not_assessed', summary_uk: '' } }], warnings_uk: [] }) }
    if (path === '/terrain-profile') return Promise.resolve({ plan_id: planId, route_id: 'transect-1', trip_date: date, status: 'available', synthetic: false, coverage: 'not_continuous', evidence_scope: 'spaced_point_samples', distance_m: total, sample_spacing_m: total / 2, points: [0, total / 2, total].map(chainage_m => ({ chainage_m, point: point(chainage_m), elevation_m: 100, land_cover_class: 10 })), sources: [], warnings_uk: [] })
    if (path === '/route-context') return Promise.resolve(change({ plan_id: planId, route_id: 'transect-1', trip_date: date, section_index: body.section_index, sections: structuredClone(sections), synthetic: false, evidence_scope: 'point_sample', coverage: 'not_continuous', status: 'partial', terrain: { elevation_m: body.sample_chainage_m ?? 100 }, land_cover: { class: 50, label: 'built_up', reference_year: 2021 }, sources: [], warnings_uk: [], ...('sample_chainage_m' in body ? { sample_selection: { kind: 'line_chainage', chainage_m: body.sample_chainage_m, point: point(body.sample_chainage_m) } } : {}) }, body))
    throw new Error(path)
  }) }
}
async function start(root: HTMLElement) { root.querySelector<HTMLButtonElement>('.reference-button')!.click(); await flush(); root.querySelector<HTMLButtonElement>('.plan-button')!.click(); await flush() }

it.each(['terrain_transect', 'terrain_candidate'] as const)('commits a different-section %s pick once and reuses the accepted plan/profile', async kind => {
  const client = fixtureClient(undefined, kind), root = document.createElement('div'), app = createApp(RoutePlanner, { client }); app.mount(root)
  try {
    await start(root); root.querySelector<HTMLButtonElement>('[data-pick="250"]')!.click(); await flush()
    const requests = client.post.mock.calls.filter(c => c[0] === '/route-context').map(c => c[1])
    expect(requests).toEqual([{ plan_id: planId, route_id: 'transect-1', section_index: 0 }, { plan_id: planId, route_id: 'transect-1', section_index: 2, sample_chainage_m: 250 }])
    expect(state.map.inspectionPoint).toEqual(point(250))
    expect(root.querySelector('.position-picker > summary')?.textContent).toContain('250 м від A')
    expect(root.querySelectorAll('.section-context > .sample-note')).toHaveLength(1)
    expect(client.post.mock.calls.filter(c => c[0] === '/terrain-profile')).toHaveLength(1)
    expect(client.post.mock.calls.filter(c => c[0] === '/terrain-path-plans')).toHaveLength(1)
    root.querySelector<HTMLButtonElement>('[data-pick="midpoint"]')!.click(); await flush()
    expect(client.post.mock.lastCall?.[1]).toEqual({ plan_id: planId, route_id: 'transect-1', section_index: 2 })
    const range = root.querySelector<HTMLInputElement>('[data-testid="sample-chainage"]')!
    expect(Number(range.value)).toBeCloseTo((sections[2].from_m + sections[2].to_m) / 2, 6)
  } finally { app.unmount() }
})

it.each([1, 2])('keeps section %i when its range minimum is an adjacent section boundary', async index => {
  const client = fixtureClient(), root = document.createElement('div'), app = createApp(RoutePlanner, { client }); app.mount(root)
  try {
    await start(root)
    root.querySelector<HTMLButtonElement>(`[data-section-index="${index}"]`)!.click(); await flush()
    const range = root.querySelector<HTMLInputElement>('[data-testid="sample-chainage"]')!
    const boundary = Number(range.min)
    range.value = range.min; range.dispatchEvent(new Event('input', { bubbles: true })); await flush()
    root.querySelector('.position-picker form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })); await flush()
    expect(client.post.mock.lastCall?.[1]).toEqual({ plan_id: planId, route_id: 'transect-1', section_index: index, sample_chainage_m: boundary })
    expect(state.map.selectedSectionIndex).toBe(index)
    expect(state.map.inspectionPoint).toEqual(point(boundary))
    expect(root.querySelector('.section-context [role="alert"]')).toBeNull()
  } finally { app.unmount() }
})

it('opens a terrain-table sample in the existing inspector with one context request and moves focus', async () => {
  const client = fixtureClient(), root = document.createElement('div'), app = createApp(RoutePlanner, { client })
  document.body.append(root); app.mount(root)
  try {
    await start(root)
    root.querySelector<HTMLButtonElement>('[aria-label="Закрити деталі"]')!.click(); await flush()
    const buttons = root.querySelectorAll<HTMLButtonElement>('[data-testid="terrain-inspect"]')
    expect(buttons).toHaveLength(3)
    buttons[1].click(); await flush()
    const calls = client.post.mock.calls.filter(c => c[0] === '/route-context')
    expect(calls).toHaveLength(2)
    expect(calls[1][1]).toEqual({ plan_id: planId, route_id: 'transect-1', section_index: 1, sample_chainage_m: total / 2 })
    expect(state.map.inspectionPoint).toEqual(point(total / 2))
    expect(root.querySelectorAll('.route-drawer')).toHaveLength(1)
    expect(document.activeElement).toBe(root.querySelector('.route-drawer h2'))
    expect(client.post.mock.calls.filter(c => c[0] === '/terrain-profile')).toHaveLength(1)
    expect(client.post.mock.calls.filter(c => c[0] === '/terrain-path-plans')).toHaveLength(1)
  } finally { app.unmount(); root.remove() }
})

it('cannot self-authenticate a wrong-point reply with its own forged section geometry', async () => {
  const client = fixtureClient((context, body) => {
    if ('sample_chainage_m' in body) {
      for (const section of context.sections) section.geometry.coordinates = section.geometry.coordinates.map(([lng, lat]: number[]) => [lng + 1, lat])
      context.sample_selection.point.longitude += 1
    }
    return context
  })
  const root = document.createElement('div'), app = createApp(RoutePlanner, { client }); app.mount(root)
  try {
    await start(root); root.querySelector<HTMLButtonElement>('[data-pick="250"]')!.click(); await flush()
    expect(root.querySelector('[role="alert"]')).not.toBeNull()
    expect(root.querySelector('.context-metrics')).toBeNull()
    expect(state.map.inspectionPoint).toBeNull()
  } finally { app.unmount() }
})

it('clears exact evidence for a later same-section pick and rejects its late predecessor', async () => {
  let resolveOld!: (value: unknown) => void
  const client = fixtureClient((context, body) => body.sample_chainage_m === 250 ? new Promise(resolve => { resolveOld = () => resolve(context) }) : context)
  const root = document.createElement('div'), app = createApp(RoutePlanner, { client }); app.mount(root)
  try {
    await start(root); root.querySelector<HTMLButtonElement>('[data-pick="250"]')!.click(); await flush()
    expect(state.map.inspectionPoint).toBeNull(); expect(root.querySelector('.context-metrics')).toBeNull()
    root.querySelector<HTMLButtonElement>('[data-pick="260"]')!.click(); await flush()
    expect(state.map.inspectionPoint).toEqual(point(260))
    resolveOld(null); await flush(); expect(state.map.inspectionPoint).toEqual(point(260))
    const mass = root.querySelector<HTMLInputElement>('input[type=number]')!; mass.value = '22'; mass.dispatchEvent(new Event('input', { bubbles: true })); await flush()
    expect(state.map.inspectionPoint).toBeNull(); expect(root.querySelector('.position-picker')).toBeNull(); expect(state.map.routes).toEqual([])
  } finally { app.unmount() }
})
