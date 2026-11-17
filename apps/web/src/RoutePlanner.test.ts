// @vitest-environment jsdom
import { createApp, nextTick } from 'vue'
import { expect, it, vi } from 'vitest'
vi.mock('./components/RouteMap.vue', () => ({ default: { props: ['landCoverTrace'], template: '<div class="map-stub" :data-trace="landCoverTrace ? \'shown\' : \'none\'"></div>' } }))
import RoutePlanner from './RoutePlanner.vue'

const flush = async () => { await Promise.resolve(); await nextTick() }

it('owns a validated profile trace and clears it when the trip is invalidated', async () => {
  const request = { trip_date: '2026-10-26' }
  const client = { get: vi.fn(), post: vi.fn().mockImplementation((path: string) => {
    if (path === '/terrain-path-plans') return Promise.resolve({ plan_id: 'a'.repeat(32), analysis_kind: 'terrain_transect', request, status: 'ready', routes: [{ id: 'transect-1', name: 'Профіль', distance_m: 100, geometry_kind: 'analysis_transect', geometry: { type: 'LineString', coordinates: [[10.73, 59.982], [10.75, 60]] }, conditions: { status: 'not_assessed', summary_uk: '' }, surface: { paved_m: null, unpaved_m: null }, segments: [] }], warnings_uk: [] })
    return Promise.resolve({ plan_id: 'a'.repeat(32), route_id: 'transect-1', trip_date: '2026-10-26', synthetic: false, status: 'partial', evidence_scope: 'spaced_point_samples', coverage: 'not_continuous', distance_m: 100, sample_spacing_m: 100, points: [{ chainage_m: 0, point: { longitude: 10.73, latitude: 59.982 }, elevation_m: 1, land_cover_class: 30, land_cover_label: 'grassland' }, { chainage_m: 100, point: { longitude: 10.75, latitude: 60 }, elevation_m: 2, land_cover_class: 80, land_cover_label: 'permanent_water' }], sources: [], warnings_uk: [], land_cover_trace: { status: 'available', evidence_scope: 'intersected_raster_cells', coverage: 'centerline_only', reference_year: 2021, resolution_m: 10, distance_m: 100, known_m: 100, unknown_m: 0, cell_count: 1, tile_attempts: 1, segments: [{ start_m: 0, end_m: 100, class_code: 30, label: 'grassland', geometry: { type: 'LineString', coordinates: [[10.73, 59.982], [10.75, 60]] } }], sources: [], warnings_uk: [] } })
  }) }
  const root = document.createElement('div'); const app = createApp(RoutePlanner, { client }); app.mount(root)
  try {
    root.querySelector<HTMLButtonElement>('.reference-button')!.click(); await flush()
    const initialDate = root.querySelector<HTMLInputElement>('input[type="date"]')!
    initialDate.value = request.trip_date; initialDate.dispatchEvent(new Event('input', { bubbles: true })); await flush()
    root.querySelector<HTMLButtonElement>('.plan-button')!.click(); await flush(); await flush()
    expect(root.querySelector('.map-stub')?.getAttribute('data-trace')).toBe('shown')
    const date = root.querySelector<HTMLInputElement>('input[type="date"]')!; date.value = '2026-10-27'; date.dispatchEvent(new Event('input', { bubbles: true })); await flush()
    expect(root.querySelector('.map-stub')?.getAttribute('data-trace')).toBe('none')
  } finally { app.unmount() }
})

it('connects details to section context using the server plan handle', async () => {
  let date = ''
  const client = { get: vi.fn(), post: vi.fn().mockImplementation((path, body) => {
    if (path === '/route-plans') { date = body.trip_date; return Promise.resolve({ request: body, plan_id: 'a'.repeat(32), status: 'ready', routes: [{ id: 'route-1', name: 'Основний', distance_m: 1000, geometry: { type: 'LineString', coordinates: [[10.74, 59.91], [10.78, 59.94]] }, conditions: { status: 'not_assessed', summary_uk: 'Умови ґрунту не оцінено' } }], warnings_uk: [] }) }
    return Promise.resolve({ plan_id: 'a'.repeat(32), route_id: 'route-1', section_index: 0, trip_date: date, status: 'partial', sections: [], sources: [], warnings_uk: [] })
  }) }
  const root = document.createElement('div'); const app = createApp(RoutePlanner, { client, initialMode: 'road' }); app.mount(root)
  try {
    root.querySelector<HTMLButtonElement>('.reference-button')!.click(); await flush()
    root.querySelector<HTMLButtonElement>('.plan-button')!.click(); await flush()
    root.querySelector<HTMLButtonElement>('[data-testid="route-details"]')!.click(); await flush()
    expect(client.post).toHaveBeenCalledWith('/route-context', { plan_id: 'a'.repeat(32), route_id: 'route-1', section_index: 0 })
    expect(root.textContent).toContain('Дані ділянки')
  } finally { app.unmount() }
})

it('starts with an honest empty trip and lets the user choose origin on the map', async () => {
  const client = { get: vi.fn(), post: vi.fn() }
  const root = document.createElement('div')
  const app = createApp(RoutePlanner, { client })
  app.mount(root)
  try {
    expect(root.textContent).toContain('Оберіть точки A і B')
    expect(root.textContent).not.toContain('Основний')
    ;(root.querySelector('[data-testid="pick-origin"]') as HTMLButtonElement).click()
    await flush()
    expect(root.textContent).toContain('Виберіть точку A на карті')
  } finally { app.unmount() }
})

it('discards a late route response after a trip input changes', async () => {
  let resolve!: (value: any) => void
  const client = { get: vi.fn(), post: vi.fn(() => new Promise(result => { resolve = result })) }
  const root = document.createElement('div')
  const app = createApp(RoutePlanner, { client, initialMode: 'road' })
  app.mount(root)
  try {
    ;[...root.querySelectorAll('button')].find(button => button.textContent?.includes('Контрольний приклад'))?.click()
    await flush()
    ;[...root.querySelectorAll('button')].find(button => button.textContent?.includes('Оновити маршрути'))?.click()
    expect(client.post).toHaveBeenCalledOnce()
    const date = root.querySelector<HTMLInputElement>('input[type="date"]')!
    date.value = date.value === '2026-11-01' ? '2026-11-02' : '2026-11-01'; date.dispatchEvent(new Event('input', { bubbles: true }))
    await flush()
    resolve({ status: 'ready', routes: [{ id: 'r-1', name: 'Основний', distance_m: 1000, geometry: { type: 'LineString', coordinates: [[10, 59], [11, 60]] }, conditions: { status: 'not_assessed', summary_uk: 'Умови ґрунту не оцінено' }, surface: { paved_m: null, unpaved_m: null }, segments: [] }], vehicle_assessment: 'not_assessed', date_assessment: 'not_assessed', synthetic: false, warnings_uk: [] })
    await flush()
    expect(root.textContent).not.toContain('Основний')
    expect(root.querySelector<HTMLButtonElement>('.plan-button')!.disabled).toBe(false)
  } finally { app.unmount() }
})

it('selects a route without automatically covering the map with details', async () => {
  const client = { get: vi.fn(), post: vi.fn().mockResolvedValue({ status: 'ready', routes: [{ id: 'r-1', name: 'Основний', distance_m: 1000, geometry: { type: 'LineString', coordinates: [[10, 59], [11, 60]] }, conditions: { status: 'not_assessed', summary_uk: 'Умови ґрунту не оцінено' }, surface: { paved_m: null, unpaved_m: null }, segments: [] }], vehicle_assessment: 'not_assessed', date_assessment: 'not_assessed', synthetic: false, warnings_uk: [] }) }
  const root = document.createElement('div')
  const app = createApp(RoutePlanner, { client, initialMode: 'road' }); app.mount(root)
  try {
    ;[...root.querySelectorAll('button')].find(button => button.textContent?.includes('Контрольний приклад'))?.click()
    await flush(); root.querySelector<HTMLButtonElement>('.plan-button')!.click(); await flush()
    expect(root.querySelector('.route-card.selected')).not.toBeNull()
    expect(root.querySelector('.route-drawer')).toBeNull()
    root.querySelector<HTMLButtonElement>('[data-testid="route-details"]')!.click(); await flush()
    expect(root.querySelector('.route-drawer')).not.toBeNull()
    root.querySelector<HTMLButtonElement>('[aria-label="Закрити деталі"]')!.click(); await flush()
    expect(root.querySelector('.route-card.selected')).not.toBeNull()
  } finally { app.unmount() }
})

it('geocodes only on explicit submit for the point currently being selected', async () => {
  const client = { get: vi.fn().mockResolvedValue({ status: 'ready', places: [{ longitude: 10.7, latitude: 59.9, label: 'Осло' }] }), post: vi.fn() }
  const root = document.createElement('div')
  const app = createApp(RoutePlanner, { client })
  app.mount(root)
  try {
    ;(root.querySelector('[data-testid="pick-origin"]') as HTMLButtonElement).click()
    const input = root.querySelector<HTMLInputElement>('input[aria-label="Пошук місця"]')!
    input.value = 'Oslo'; input.dispatchEvent(new Event('input', { bubbles: true }))
    await flush()
    expect(client.get).not.toHaveBeenCalled()
    input.closest('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
    await flush()
    expect(client.get).toHaveBeenCalledWith('/places?q=Oslo')
    expect(root.textContent).toContain('Осло')
  } finally { app.unmount() }
})

it('assigns an explicit latitude, longitude pair locally without geocoding', async () => {
  const client = { get: vi.fn(), post: vi.fn() }
  const root = document.createElement('div')
  const app = createApp(RoutePlanner, { client })
  app.mount(root)
  try {
    ;(root.querySelector('[data-testid="pick-origin"]') as HTMLButtonElement).click()
    const input = root.querySelector<HTMLInputElement>('input[aria-label="Пошук місця"]')!
    input.value = '59.9139, 10.7387'; input.dispatchEvent(new Event('input', { bubbles: true }))
    input.closest('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
    await flush()
    expect(client.get).not.toHaveBeenCalled()
    expect(root.textContent).toContain('59.91390, 10.73870')
    expect(root.textContent).toContain('Оберіть точки A і B')
  } finally { app.unmount() }
})

it('reports an invalid coordinate-looking query locally instead of geocoding it', async () => {
  const client = { get: vi.fn(), post: vi.fn() }
  const root = document.createElement('div')
  const app = createApp(RoutePlanner, { client })
  app.mount(root)
  try {
    ;(root.querySelector('[data-testid="pick-origin"]') as HTMLButtonElement).click()
    const input = root.querySelector<HTMLInputElement>('input[aria-label="Пошук місця"]')!
    input.value = '91, 10'; input.dispatchEvent(new Event('input', { bubbles: true }))
    input.closest('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
    await flush()
    expect(client.get).not.toHaveBeenCalled()
    expect(root.textContent).toContain('Широта має бути від -90 до 90, довгота — від -180 до 180.')
  } finally { app.unmount() }
})

it('keeps place input editable while a search is pending and ignores its stale result', async () => {
  let resolve!: (value: any) => void
  const client = { get: vi.fn(() => new Promise(result => { resolve = result })), post: vi.fn() }
  const root = document.createElement('div')
  const app = createApp(RoutePlanner, { client })
  app.mount(root)
  try {
    ;(root.querySelector('[data-testid="pick-origin"]') as HTMLButtonElement).click()
    const input = root.querySelector<HTMLInputElement>('input[aria-label="Пошук місця"]')!
    input.value = 'Oslo'; input.dispatchEvent(new Event('input', { bubbles: true }))
    input.closest('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
    await flush()
    expect(input.disabled).toBe(false)
    input.value = 'Bergen'; input.dispatchEvent(new Event('input', { bubbles: true }))
    resolve({ status: 'ready', places: [{ longitude: 10.7, latitude: 59.9, label: 'Старий результат' }] })
    await flush()
    expect(root.textContent).not.toContain('Старий результат')
  } finally { app.unmount() }
})

it('uses the browser-local date for the control example', async () => {
  vi.useFakeTimers()
  vi.setSystemTime(new Date(2026, 9, 26, 12))
  const iso = vi.spyOn(Date.prototype, 'toISOString').mockReturnValue('2000-01-01T00:00:00.000Z')
  const root = document.createElement('div')
  const app = createApp(RoutePlanner, { client: { get: vi.fn(), post: vi.fn() } })
  app.mount(root)
  try {
    ;[...root.querySelectorAll('button')].find(button => button.textContent?.includes('Контрольний приклад'))?.click()
    await flush()
    expect(root.querySelector<HTMLInputElement>('input[type="date"]')!.value).toBe('2026-10-26')
  } finally { app.unmount(); iso.mockRestore(); vi.useRealTimers() }
})

it.each(['date', 'mass', 'vehicle'])('binds the offroad trip inspector to the accepted plan and clears it after %s changes', async field => {
  let accepted: any
  const client = { get: vi.fn(), post: vi.fn().mockImplementation((path, body) => {
    if (path === '/terrain-path-plans') {
      accepted = body
      return Promise.resolve({ plan_id: 'a'.repeat(32), analysis_kind: 'terrain_candidate', request: body, status: 'ready', routes: [{ id: 'transect-1', name: 'Кандидат шляху', distance_m: 1000, geometry_kind: 'terrain_candidate', geometry: { type: 'LineString', coordinates: [[10.73, 59.982], [10.75, 60]] }, conditions: { status: 'not_assessed', summary_uk: 'Проїзд не підтверджено.' } }], warnings_uk: [] })
    }
    if (path === '/route-context') return Promise.resolve({ plan_id: 'a'.repeat(32), route_id: 'transect-1', section_index: 0, trip_date: accepted.trip_date, status: 'partial', sections: [], sources: [], warnings_uk: [] })
    return Promise.resolve({ plan_id: 'a'.repeat(32), route_id: 'transect-1', trip_date: accepted.trip_date, status: 'unavailable', synthetic: false, evidence_scope: 'spaced_point_samples', coverage: 'not_continuous', distance_m: 1000, sample_spacing_m: 250, points: [], sources: [], warnings_uk: [] })
  }) }
  const root = document.createElement('div'), app = createApp(RoutePlanner, { client }); app.mount(root)
  try {
    root.querySelector<HTMLButtonElement>('.reference-button')!.click(); await flush()
    const mass = root.querySelector<HTMLInputElement>('input[type="number"]')!
    mass.value = '20.25'; mass.dispatchEvent(new Event('input', { bubbles: true })); await flush()
    root.querySelector<HTMLButtonElement>('.plan-button')!.click(); await flush(); await flush()
    expect(root.querySelector('.route-drawer h2')?.textContent).toBe('Умови для поїздки')
    expect(root.querySelector('.trip-request')?.textContent).toContain('Вантажівка 6×6 · 20,25 т')
    expect(root.querySelector('.trip-request')?.textContent).toContain(accepted.trip_date)
    expect(root.querySelector('details.terrain-details')).not.toBeNull()
    expect(client.post.mock.calls.map(call => call[0]).sort()).toEqual(['/route-context', '/terrain-path-plans', '/terrain-profile'].sort())
    const input = root.querySelector<HTMLInputElement | HTMLSelectElement>(field === 'date' ? 'input[type="date"]' : field === 'mass' ? 'input[type="number"]' : 'select')!
    input.value = field === 'date' ? '2026-11-01' : field === 'mass' ? '22.5' : 'car'
    input.dispatchEvent(new Event(field === 'vehicle' ? 'change' : 'input', { bubbles: true })); await flush()
    expect(root.querySelector('.trip-request')).toBeNull()
    expect(root.querySelector('.route-drawer')).toBeNull()
    expect(client.post).toHaveBeenCalledTimes(3)
    expect(root.querySelector<HTMLButtonElement>('.plan-button')!.disabled).toBe(false)
  } finally { app.unmount() }
})

