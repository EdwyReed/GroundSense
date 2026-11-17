// @vitest-environment jsdom
import { createApp, h, nextTick, reactive } from 'vue'
import { afterEach, expect, it, vi } from 'vitest'
import RouteMap from './RouteMap.vue'
const viewport = { width: window.innerWidth, height: window.innerHeight }
const landCoverTrace = {
  status: 'partial' as const, evidence_scope: 'intersected_raster_cells' as const, coverage: 'centerline_only' as const, reference_year: 2021 as const, resolution_m: 10 as const,
  distance_m: 100, known_m: 60, unknown_m: 40, cell_count: 2, tile_attempts: 1, sources: [], warnings_uk: [],
  segments: [
    { start_m: 0, end_m: 60, class_code: 30 as const, label: 'grassland', geometry: { type: 'LineString' as const, coordinates: [[10, 59], [10.5, 59.5]] as [number, number][] } },
    { start_m: 60, end_m: 100, class_code: null, label: null, geometry: { type: 'LineString' as const, coordinates: [[10.5, 59.5], [11, 60]] as [number, number][] } },
  ],
}

const state = vi.hoisted(() => ({ options: {} as any, events: {} as Record<string, Function>, sources: {} as Record<string, any>, layers: [] as any[], filters: vi.fn(), fit: vi.fn(), query: vi.fn(), remove: vi.fn(), markers: [] as any[] }))
vi.mock('maplibre-gl', () => ({ setWorkerUrl: vi.fn(), NavigationControl: class {}, Map: class {
  constructor(options: any) { state.options = options }
  on(name: string, layerOrCallback: any, callback?: any) { const key = callback ? `${name}:${layerOrCallback}` : name, listener = callback || layerOrCallback, previous = state.events[key]; state.events[key] = previous ? (...args: any[]) => { previous(...args); listener(...args) } : listener; return this }
  addControl() {} addSource(id: string, source: any) { state.sources[id] = { ...source, setData(data: any) { this.data = data } } } addLayer(layer: any, beforeId?: string) { state.layers.push({ ...layer, beforeId }) }
  getSource(id: string) { return state.sources[id] } getLayer() { return true } isStyleLoaded() { return true }
  setFilter(...args: any[]) { state.filters(...args) } fitBounds(...args: any[]) { state.fit(...args) } queryRenderedFeatures(...args: any[]) { return state.query(...args) } getCanvas() { return { style: {} } } remove() { state.remove() }
}, Marker: class {
  element: HTMLElement; longitude = 0; latitude = 0; positioned = false
  constructor(options: any) { this.element = options.element; state.markers.push(this) }
  setLngLat(point: [number, number]) { [this.longitude, this.latitude] = point; this.positioned = true; return this }
  getElement() { return this.element }
  addTo() { if (!this.positioned) throw new Error('MapLibre projects the marker position during addTo'); return this } remove() {}
} }))
afterEach(() => { state.options = {}; state.events = {}; state.sources = {}; state.layers = []; state.markers = []; state.filters.mockClear(); state.fit.mockClear(); state.query.mockReset(); state.remove.mockClear(); Object.defineProperty(window, 'innerWidth', { configurable: true, value: viewport.width }); Object.defineProperty(window, 'innerHeight', { configurable: true, value: viewport.height }) })

it('uses a live MapLibre basemap, renders actual route geometry, and sends an A/B map pick', () => {
  const picked = vi.fn()
  const root = document.createElement('div')
  const app = createApp(RouteMap, { origin: null, destination: null, selecting: 'origin', selectedRouteId: 'route-1', routes: [{ id: 'route-1', name: 'Основний', distance_m: 10, geometry: { type: 'LineString', coordinates: [[10, 59], [11, 60]] }, conditions: { status: 'not_assessed', summary_uk: '' }, surface: { paved_m: null, unpaved_m: null }, segments: [] }], onPoint: picked })
  app.mount(root)
  try {
    expect(state.options.style).toBe('https://tiles.openfreemap.org/styles/liberty')
    state.events.load()
    expect(state.sources['route-plans'].data.features[0].geometry.coordinates).toEqual([[10, 59], [11, 60]])
    state.events.click({ lngLat: { lng: 10.2, lat: 59.2 } })
    expect(picked).toHaveBeenCalledWith({ longitude: 10.2, latitude: 59.2, label: 'Точка A' })
    expect(state.filters).toHaveBeenCalledWith('route-selected', ['==', ['get', 'id'], 'route-1'])
    expect(state.fit.mock.calls[0][0]).toEqual([[10, 59], [11, 60]])
  } finally { app.unmount() }
})

it('uses labeled keyboard buttons for endpoints and emits their selection', () => {
  const selected = vi.fn()
  const root = document.createElement('div')
  const app = createApp(RouteMap, { origin: { longitude: 10, latitude: 59, label: 'Oslo' }, destination: { longitude: 11, latitude: 60, label: 'Bergen' }, selecting: null, selectedRouteId: null, routes: [], onSelectPoint: selected })
  app.mount(root)
  try {
    state.events.load()
    expect(state.markers).toHaveLength(2)
    const originMarker = state.markers[0].element as HTMLButtonElement
    expect(originMarker.tagName).toBe('BUTTON')
    expect(originMarker.getAttribute('aria-label')).toContain('Точка A')
    expect(originMarker.getAttribute('aria-label')).toContain('59.00000, 10.00000')
    expect(originMarker.textContent).toBe('A')
    originMarker.click()
    expect(selected).toHaveBeenCalledWith('origin')
  } finally { app.unmount() }
})

it('keeps responsive fit padding non-negative in a short mobile viewport', () => {
  Object.defineProperty(window, 'innerWidth', { configurable: true, value: 600 })
  Object.defineProperty(window, 'innerHeight', { configurable: true, value: 40 })
  const root = document.createElement('div')
  const app = createApp(RouteMap, { origin: { longitude: 10, latitude: 59 }, destination: { longitude: 11, latitude: 60 }, selecting: null, selectedRouteId: null, routes: [] })
  app.mount(root)
  try {
    state.events.load()
    expect(state.fit.mock.calls[0][1].padding.bottom).toBeGreaterThanOrEqual(0)
  } finally { app.unmount() }
})

it('renders the inspected section and its sample separately from the whole route', () => {
  const root = document.createElement('div')
  const inspectedSection = { index: 1, from_m: 100, to_m: 200, point: { longitude: 10.75, latitude: 59.92 }, geometry: { type: 'LineString' as const, coordinates: [[10.74, 59.91], [10.76, 59.93]] as [number, number][] } }
  const app = createApp(RouteMap, { origin: null, destination: null, selecting: null, selectedRouteId: null, routes: [], inspectedSection }); app.mount(root)
  try {
    state.events.load()
    expect(state.sources['inspection-section']).toBeDefined()
    expect(state.sources['inspection-section'].data.features[0].geometry).toEqual(inspectedSection.geometry)
    expect(state.sources['inspection-section'].data.features[1].geometry.coordinates).toEqual([10.75, 59.92])
  } finally { app.unmount() }
})

it('clears an older loaded point sample while a different section is selected', () => {
  const root = document.createElement('div')
  const inspectedSection = { index: 1, from_m: 100, to_m: 200, point: { longitude: 10.75, latitude: 59.92 }, geometry: { type: 'LineString' as const, coordinates: [[10.74, 59.91], [10.76, 59.93]] as [number, number][] } }
  const app = createApp(RouteMap, { origin: null, destination: null, selecting: null, selectedRouteId: null, routes: [], inspectedSection, selectedSectionIndex: 2 }); app.mount(root)
  try {
    state.events.load()
    expect(state.sources['inspection-section'].data.features).toEqual([])
  } finally { app.unmount() }
})

it('previews a server section without refitting and exposes an accessible sample marker', () => {
  const previewed = vi.fn()
  const sections = [{ index: 0, from_m: 0, to_m: 100, point: { longitude: 10.75, latitude: 59.92 }, geometry: { type: 'LineString' as const, coordinates: [[10.74, 59.91], [10.76, 59.93]] as [number, number][] } }]
  const root = document.createElement('div')
  const app = createApp(RouteMap, { origin: null, destination: null, selecting: null, selectedRouteId: 'route-1', routes: [], inspecting: true, sections, selectedSectionIndex: 0, previewSectionIndex: 0, onPreviewSection: previewed })
  app.mount(root)
  try {
    state.events.load()
    const marker = state.markers[0].element as HTMLButtonElement
    expect(marker.dataset.mapSectionIndex).toBe('0')
    expect(marker.getAttribute('aria-label')).toContain('точка вибірки даних')
    expect(marker.getAttribute('aria-pressed')).toBe('true')
    expect(state.sources['section-preview'].data.features[0].geometry).toEqual(sections[0].geometry)
    const fitCalls = state.fit.mock.calls.length
    marker.dispatchEvent(new FocusEvent('focus'))
    expect(previewed).toHaveBeenCalledWith(0)
    marker.dispatchEvent(new FocusEvent('blur')); expect(previewed).toHaveBeenLastCalledWith(null)
    marker.dispatchEvent(new MouseEvent('mouseenter')); expect(previewed).toHaveBeenLastCalledWith(0)
    marker.dispatchEvent(new MouseEvent('mouseleave')); expect(previewed).toHaveBeenLastCalledWith(null)
    expect(state.fit.mock.calls).toHaveLength(fitCalls)
  } finally { app.unmount() }
})

it.each(['road_route', 'analysis_transect'])('does not emit a whole-route selection when a section hit owns a %s click', geometryKind => {
  const selectedRoute = vi.fn()
  const sections = [{ index: 0, from_m: 0, to_m: 100, point: { longitude: 10.75, latitude: 59.92 }, geometry: { type: 'LineString' as const, coordinates: [[10.74, 59.91], [10.76, 59.93]] as [number, number][] } }]
  const root = document.createElement('div')
  const app = createApp(RouteMap, { origin: null, destination: null, selecting: null, selectedRouteId: 'route-1', routes: [{ id: 'route-1', geometry_kind: geometryKind as 'road_route' | 'analysis_transect', name: 'Основний', distance_m: 10, geometry: sections[0].geometry, conditions: { status: 'not_assessed', summary_uk: '' }, surface: { paved_m: null, unpaved_m: null }, segments: [] }], inspecting: true, sections, onRoute: selectedRoute })
  app.mount(root)
  try {
    state.events.load()
    state.query.mockReturnValue([{ properties: { index: 0 } }])
    state.events[geometryKind === 'analysis_transect' ? 'click:analysis-lines' : 'click:route-lines']({ point: { x: 1, y: 1 }, features: [{ properties: { id: 'route-1' } }] })
    expect(selectedRoute).not.toHaveBeenCalled()
  } finally { app.unmount() }
})

it('updates preview when moving between connected sections without leaving the hit layer', () => {
  const preview = vi.fn()
  const sections = [0, 1].map(index => ({ index, from_m: index * 100, to_m: (index + 1) * 100, point: { longitude: 10.75, latitude: 59.92 }, geometry: { type: 'LineString' as const, coordinates: [[10.74, 59.91], [10.76, 59.93]] as [number, number][] } }))
  const root = document.createElement('div'), app = createApp(RouteMap, { origin: null, destination: null, selecting: null, selectedRouteId: 'route-1', routes: [], inspecting: true, sections, onPreviewSection: preview }); app.mount(root)
  try {
    state.events.load()
    const fits = state.fit.mock.calls.length
    for (const index of [0, 1]) state.events['mousemove:section-hit']({ features: [{ properties: { index } }] })
    expect(preview.mock.calls).toEqual([[0], [1]])
    expect(state.sources['inspection-section'].data.features).toEqual([])
    expect(state.fit).toHaveBeenCalledTimes(fits)
  } finally { app.unmount() }
})

it('selects the clicked server-bound section from the transparent hit layer', () => {
  const selected = vi.fn()
  const sections = [{ index: 2, from_m: 200, to_m: 300, point: { longitude: 10.75, latitude: 59.92 }, geometry: { type: 'LineString' as const, coordinates: [[10.74, 59.91], [10.76, 59.93]] as [number, number][] } }]
  const root = document.createElement('div')
  const app = createApp(RouteMap, { origin: null, destination: null, selecting: null, selectedRouteId: null, routes: [], inspecting: true, sections, selectedSectionIndex: 2, onSection: selected })
  app.mount(root)
  try {
    state.events.load()
    expect(state.sources['inspectable-sections'].data.features[0].properties).toEqual({ index: 2, route_id: null })
    expect(state.layers.find(layer => layer.id === 'section-hit').paint['line-opacity']).toBe(0)
    state.events['click:section-hit']({ features: [{ properties: { index: 2 } }] })
    expect(selected).toHaveBeenCalledWith(2)
  } finally { app.unmount() }
})

it('reserves desktop inspector space when fitting route endpoints', () => {
  const root = document.createElement('div')
  const app = createApp(RouteMap, { origin: { longitude: 10, latitude: 59 }, destination: { longitude: 11, latitude: 60 }, selecting: null, selectedRouteId: null, routes: [], inspecting: true }); app.mount(root)
  try {
    state.events.load()
    expect(state.fit.mock.calls[0][1].padding.right).toBeGreaterThanOrEqual(400)
  } finally { app.unmount() }
})

it('draws analysis transects dashed and never as a selected solid road route', () => {
  const root = document.createElement('div')
  const app = createApp(RouteMap, { origin: null, destination: null, selecting: null, selectedRouteId: 'transect-1', routes: [{ id: 'transect-1', geometry_kind: 'analysis_transect', name: 'Профіль', distance_m: 1000, geometry: { type: 'LineString', coordinates: [[10.73, 59.982], [10.75, 60]] }, conditions: { status: 'not_assessed', summary_uk: '' }, surface: { paved_m: null, unpaved_m: null }, segments: [] }] }); app.mount(root)
  try {
    state.events.load()
    expect(state.sources['route-plans'].data.features[0].properties.kind).toBe('analysis_transect')
    expect(state.layers.find(layer => layer.id === 'analysis-lines').paint['line-dasharray']).toEqual([2, 2])
    expect(state.filters).toHaveBeenCalledWith('route-selected', ['==', ['get', 'id'], ''])
  } finally { app.unmount() }
})

it('switches validated static WorldCover segments without refitting or changing route controls', async () => {
  const root = document.createElement('div')
  const app = createApp(RouteMap, { origin: null, destination: null, selecting: null, selectedRouteId: 'route-1', routes: [], landCoverTrace }); app.mount(root)
  try {
    state.events.load()
    expect(root.textContent).toContain('Покрив · 2021')
    expect(state.sources['land-cover-trace'].data.features).toEqual([])
    const fits = state.fit.mock.calls.length
    root.querySelector<HTMLButtonElement>('[aria-label="Покрив · 2021"]')!.click()
    await nextTick()
    expect(state.sources['land-cover-trace'].data.features).toHaveLength(2)
    expect(state.sources['land-cover-trace'].data.features[1].properties.unknown).toBe(true)
    expect(state.layers.find(layer => layer.id === 'land-cover-known').beforeId).toBe('analysis-lines')
    expect(state.layers.find(layer => layer.id === 'land-cover-unknown').beforeId).toBe('analysis-lines')
    expect(root.querySelector('.land-cover-legend')?.textContent).toContain('Трав’яний покрив')
    expect(root.querySelector('.land-cover-legend')?.textContent).toContain('Покрив невідомий')
    expect(state.fit).toHaveBeenCalledTimes(fits)
  } finally { app.unmount() }
})

it('clears the static-cover source when its owned trace is withdrawn', async () => {
  const binding: any = reactive({ origin: null, destination: null, selecting: null, selectedRouteId: null, routes: [], landCoverTrace })
  const root = document.createElement('div'); const app = createApp({ render: () => h(RouteMap, binding) }); app.mount(root)
  try {
    state.events.load(); root.querySelector<HTMLButtonElement>('[aria-label="Покрив · 2021"]')!.click(); await nextTick()
    expect(state.sources['land-cover-trace'].data.features).toHaveLength(2)
    binding.landCoverTrace = null; await nextTick()
    expect(state.sources['land-cover-trace'].data.features).toEqual([])
  } finally { app.unmount() }
})

it('highlights a selected heuristic candidate in cobalt dashes rather than as a confirmed road route', () => {
  const root = document.createElement('div'), app = createApp(RouteMap, { origin: null, destination: null, selecting: null, selectedRouteId: 'candidate-1', routes: [{ id: 'candidate-1', name: 'Кандидат', distance_m: 2290, geometry_kind: 'terrain_candidate', geometry: { type: 'LineString', coordinates: [[10.73, 59.982], [10.74, 59.998], [10.75, 60]] }, conditions: { status: 'not_assessed', summary_uk: '' } }] }); app.mount(root)
  try {
    state.events.load()
    const selected = state.layers.find(layer => layer.id === 'candidate-selected')
    expect(selected?.paint['line-color']).toBe('#1468f4')
    expect(selected?.paint['line-dasharray']).toEqual([2, 2])
    expect(state.filters).toHaveBeenCalledWith('candidate-selected', ['==', ['get', 'id'], 'candidate-1'])
    expect(state.filters).toHaveBeenCalledWith('route-selected', ['==', ['get', 'id'], ''])
  } finally { app.unmount() }
})

it.each(['analysis_transect', 'terrain_candidate'] as const)('commits one %s position when both the visible and transparent layers receive a click', geometry_kind => {
  const onSection = vi.fn(), onLineChainage = vi.fn(), onRoute = vi.fn()
  const geometry = { type: 'LineString' as const, coordinates: [[10.73, 59.982], [10.75, 60]] as [number, number][] }
  const sections = [{ index: 0, from_m: 0, to_m: 100, point: { longitude: 10.73, latitude: 59.982 }, geometry }]
  const root = document.createElement('div'), app = createApp(RouteMap, { origin: null, destination: null, selecting: null, selectedRouteId: 'transect-1', inspecting: true, sections, routes: [{ id: 'transect-1', name: 'Профіль', distance_m: 2290, geometry_kind, geometry, conditions: { status: 'not_assessed', summary_uk: '' } }], onSection, onLineChainage, onRoute }); app.mount(root)
  try {
    state.events.load(); state.query.mockReturnValue([{ properties: { index: 0 } }])
    const event = { point: { x: 1, y: 1 }, lngLat: { lng: 10.744, lat: 59.9946 }, features: [{ properties: { id: 'transect-1', index: 0 } }] }
    state.events['click:analysis-lines'](event); state.events['click:section-hit'](event)
    expect(onLineChainage).toHaveBeenCalledOnce()
    expect(onSection).not.toHaveBeenCalled(); expect(onRoute).not.toHaveBeenCalled()
  } finally { app.unmount() }
})
