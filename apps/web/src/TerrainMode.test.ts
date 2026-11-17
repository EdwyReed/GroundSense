// @vitest-environment jsdom
import { createApp, nextTick } from 'vue'
import { expect, it, vi } from 'vitest'
vi.mock('./components/RouteMap.vue', () => ({ default: { template: '<div class="map-stub"></div>' } }))
import RoutePlanner from './RoutePlanner.vue'
const flush = async () => { await Promise.resolve(); await nextTick(); await Promise.resolve(); await nextTick() }

it('defaults to off-road candidate pathfinding rather than a straight transect or road route', async () => {
  let selectedDate = ''
  const client = { get: vi.fn(), post: vi.fn().mockImplementation((path, body) => {
    if (path.endsWith('-plans')) { selectedDate = body.trip_date; return Promise.resolve({ request: body, analysis_kind: 'terrain_candidate', plan_id: 'b'.repeat(32), status: 'ready', routes: [{ id: 'terrain-path-1', name: 'За покривом і DSM', distance_m: 2200, geometry_kind: 'terrain_candidate', geometry: { type: 'LineString', coordinates: [[10.73, 59.982], [10.732, 59.996], [10.75, 60]] }, conditions: { status: 'not_assessed', summary_uk: 'Кандидат по місцевості · проїзд не підтверджено' } }], source: { id: 'terrain-search-grid', profile: 'heuristic_area_candidate' }, warnings_uk: ['Дата й маса не змінюють пошук'] }) }
    if (path === '/terrain-profile') return Promise.resolve({ plan_id: 'b'.repeat(32), route_id: 'terrain-path-1', trip_date: selectedDate, synthetic: false, evidence_scope: 'spaced_point_samples', coverage: 'not_continuous', distance_m: 200, sample_spacing_m: 200, points: [0, 200].map(chainage_m => ({ chainage_m, point: { latitude: 59.982, longitude: 10.73 }, elevation_m: 10, land_cover_class: 10, land_cover_label: 'tree_cover' })), sources: [], warnings_uk: [] })
    return Promise.resolve({ plan_id: 'b'.repeat(32), route_id: 'transect-1', section_index: 0, trip_date: '2026-10-26', sections: [], sources: [], warnings_uk: [] })
  }) }
  const root = document.createElement('div'); const app = createApp(RoutePlanner, { client }); app.mount(root)
  try {
    expect(root.querySelector('[data-mode="terrain"]')?.getAttribute('aria-pressed')).toBe('true')
    root.querySelector<HTMLButtonElement>('.reference-button')!.click(); await flush()
    root.querySelector<HTMLButtonElement>('.plan-button')!.click(); await flush()
    expect(client.post.mock.calls[0][0]).toBe('/terrain-path-plans')
    expect(client.post.mock.calls[0][1].origin).toMatchObject({ longitude: 32.536, latitude: 50.253 })
    expect(client.post.mock.calls[0][1].destination).toMatchObject({ longitude: 32.56, latitude: 50.267 })
    expect(root.querySelector('.reference-button')?.textContent).toContain('Удаю')
    expect(root.textContent).toContain('Кандидат · проїзд не підтверджено.')
    expect(root.querySelector('.route-results h2')?.textContent).toContain('Кандидати шляху')
    expect(root.textContent).toContain('Дата й маса')
    expect(root.textContent).not.toContain('Джерело: OSRM')
    expect(root.querySelector('.route-drawer')).not.toBeNull()
    expect(client.post).toHaveBeenCalledWith('/terrain-profile', { plan_id: 'b'.repeat(32), route_id: 'terrain-path-1' })
    expect(root.querySelector('.terrain-profile svg')).not.toBeNull()
    root.querySelector<HTMLButtonElement>('[data-mode="road"]')!.click(); await flush()
    expect(root.querySelector('.route-card')).toBeNull()
    expect(root.querySelector('.route-drawer')).toBeNull()
    expect(root.querySelector('.terrain-profile')).toBeNull()
  } finally { app.unmount() }
})
