<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as maplibregl from 'maplibre-gl'
import mapWorkerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?url'
import 'maplibre-gl/dist/maplibre-gl.css'
import type { LngLat, RouteAlternative } from '../lib/routeTypes'
import { isTerrainGeometry } from '../lib/routeTypes'
import type { RouteSection } from '../lib/sectionContextTypes'
import { coverClassification, type LandCoverTrace } from '../lib/landCoverTraceTypes'
import { closestPolylineChainage } from '../lib/transectSelection'

maplibregl.setWorkerUrl(mapWorkerUrl)
const props = defineProps<{ origin: LngLat | null; destination: LngLat | null; routes: RouteAlternative[]; selectedRouteId: string | null; selecting: 'origin' | 'destination' | null; inspectedSection?: RouteSection | null; inspectionPoint?: LngLat | null; inspecting?: boolean; sections?: RouteSection[]; selectedSectionIndex?: number; previewSectionIndex?: number | null; landCoverTrace?: LandCoverTrace | null }>()
const emit = defineEmits<{ point: [point: LngLat]; selectPoint: [kind: 'origin' | 'destination']; route: [id: string]; section: [index: number]; lineChainage: [chainage: number]; previewSection: [index: number | null]; status: [message: string] }>()
const root = ref<HTMLDivElement>()
let map: maplibregl.Map | undefined
let ready = false
let endpointMarkers: maplibregl.Marker[] = []
const sectionMarkers = new Map<number, maplibregl.Marker>()
const showLandCover = ref(false)
const landCoverLegend = computed(() => [...new Set(props.landCoverTrace?.segments.map(segment => segment.class_code) || [])].map(code => ({ code, ...coverClassification(code) })))
const featureCollection = () => ({ type: 'FeatureCollection' as const, features: props.routes.map(route => ({ type: 'Feature' as const, properties: { id: route.id, kind: route.geometry_kind || 'road_route' }, geometry: route.geometry })) })
const sectionControlsActive = () => Boolean(props.inspecting && !props.selecting)
const currentSections = () => sectionControlsActive() ? (props.sections || []) : []
const sectionFeatureCollection = () => ({ type: 'FeatureCollection' as const, features: currentSections().map(section => ({ type: 'Feature' as const, properties: { index: section.index, route_id: props.selectedRouteId }, geometry: section.geometry })) })
const sectionByIndex = (index: number | null | undefined) => currentSections().find(section => section.index === index)
const landCoverFeatures = () => showLandCover.value && props.landCoverTrace ? props.landCoverTrace.segments.map(segment => ({ type: 'Feature' as const, properties: { color: coverClassification(segment.class_code).color, unknown: segment.class_code === null, label: coverClassification(segment.class_code).label }, geometry: segment.geometry })) : []
function updateLandCover() { if (map && ready) (map.getSource('land-cover-trace') as maplibregl.GeoJSONSource | undefined)?.setData({ type: 'FeatureCollection', features: landCoverFeatures() } as any) }
function emitSection(index: number) { if (!props.selecting && sectionByIndex(index)) emit('section', index) }
function emitPreview(index: number | null) { if (!props.selecting && (index === null || sectionByIndex(index))) emit('previewSection', index) }
function emitLineSelection(event: { lngLat?: { lng: number; lat: number } }) {
  const route = props.routes.find(candidate => candidate.id === props.selectedRouteId && isTerrainGeometry(candidate.geometry_kind))
  const selected = route && props.inspecting && !props.selecting && currentSections().length && event.lngLat ? closestPolylineChainage(route.geometry.coordinates, { longitude: event.lngLat.lng, latitude: event.lngLat.lat }) : null
  if (!selected) return false
  emit('lineChainage', selected.chainage_m)
  return true
}
function updateSection() {
  if (!map || !ready) return
  const section = props.selectedSectionIndex !== undefined && props.inspectedSection?.index !== props.selectedSectionIndex ? null : props.inspectedSection
  const features = section ? [
    { type: 'Feature', properties: {}, geometry: section.geometry },
    { type: 'Feature', properties: {}, geometry: { type: 'Point', coordinates: [props.inspectionPoint?.longitude ?? section.point.longitude, props.inspectionPoint?.latitude ?? section.point.latitude] } },
  ] : []
  ;(map.getSource('inspection-section') as maplibregl.GeoJSONSource | undefined)?.setData({ type: 'FeatureCollection', features } as any)
}
function updateEndpointMarkers() {
  endpointMarkers.forEach(marker => marker.remove()); endpointMarkers = []
  if (!map) return
  for (const [kind, point] of [['origin', props.origin], ['destination', props.destination]] as const) {
    if (!point) continue
    const letter = kind === 'origin' ? 'A' : 'B', button = document.createElement('button')
    button.type = 'button'; button.className = 'route-endpoint-marker'; button.textContent = letter
    const coordinates = `${point.latitude.toFixed(5)}, ${point.longitude.toFixed(5)}`
    button.setAttribute('aria-label', `Точка ${letter}: ${point.label || coordinates}. Координати: ${coordinates}. Натисніть, щоб змінити точку.`)
    button.addEventListener('click', event => { event.stopPropagation(); emit('selectPoint', kind) })
    endpointMarkers.push(new maplibregl.Marker({ element: button }).setLngLat([point.longitude, point.latitude]).addTo(map))
  }
}
function updateSectionControls() {
  if (!map || !ready) return
  ;(map.getSource('inspectable-sections') as maplibregl.GeoJSONSource | undefined)?.setData(sectionFeatureCollection() as any)
  const preview = sectionByIndex(props.previewSectionIndex)
  ;(map.getSource('section-preview') as maplibregl.GeoJSONSource | undefined)?.setData({ type: 'FeatureCollection', features: preview ? [{ type: 'Feature', properties: { index: preview.index }, geometry: preview.geometry }] : [] } as any)
  const active = new Set(currentSections().map(section => section.index))
  for (const [index, marker] of sectionMarkers) if (!active.has(index)) { marker.remove(); sectionMarkers.delete(index) }
  for (const section of currentSections()) {
    let marker = sectionMarkers.get(section.index)
    if (!marker) {
      const button = document.createElement('button')
      button.type = 'button'; button.className = 'route-section-marker'; button.textContent = String(section.index + 1)
      button.dataset.mapSectionIndex = String(section.index)
      button.setAttribute('aria-label', `Ділянка ${section.index + 1}: точка вибірки даних. Натисніть, щоб обрати ділянку.`)
      button.addEventListener('click', event => { event.stopPropagation(); emitSection(section.index) })
      button.addEventListener('focus', () => emitPreview(section.index))
      button.addEventListener('blur', () => emitPreview(null))
      button.addEventListener('mouseenter', () => emitPreview(section.index))
      button.addEventListener('mouseleave', () => emitPreview(null))
      marker = new maplibregl.Marker({ element: button }).setLngLat([section.point.longitude, section.point.latitude]).addTo(map)
      sectionMarkers.set(section.index, marker)
    }
    marker.setLngLat([section.point.longitude, section.point.latitude])
    marker.getElement().setAttribute('aria-pressed', String(props.selectedSectionIndex === section.index))
  }
}
function update() {
  if (!map || !ready) return
  ;(map.getSource('route-plans') as maplibregl.GeoJSONSource | undefined)?.setData(featureCollection() as any)
  updateEndpointMarkers()
  const selected = props.routes.find(route => route.id === props.selectedRouteId)
  if (map.getLayer('route-selected')) map.setFilter('route-selected', ['==', ['get', 'id'], isTerrainGeometry(selected?.geometry_kind) ? '' : props.selectedRouteId || ''])
  if (map.getLayer('candidate-selected')) map.setFilter('candidate-selected', ['==', ['get', 'id'], selected?.geometry_kind === 'terrain_candidate' ? props.selectedRouteId || '' : ''])
  const coordinates = props.routes.flatMap(route => route.geometry.coordinates)
  if (!coordinates.length) for (const point of [props.origin, props.destination]) if (point) coordinates.push([point.longitude, point.latitude])
  if (coordinates.length >= 2) {
    const longitudes = coordinates.map(point => point[0]), latitudes = coordinates.map(point => point[1])
    const mobile = window.innerWidth <= 700, viewportHeight = Math.max(0, window.innerHeight)
    const bottom = mobile ? Math.max(0, Math.min(Math.round(viewportHeight * .62), viewportHeight - 60)) : 60
    const mapWidth = root.value?.clientWidth || Math.max(180, window.innerWidth - (mobile ? 0 : 380))
    const right = !mobile && props.inspecting ? Math.min(414, Math.max(45, mapWidth - 120)) : 45
    map.fitBounds([[Math.min(...longitudes), Math.min(...latitudes)], [Math.max(...longitudes), Math.max(...latitudes)]], { padding: { top: 60, left: 45, right, bottom }, maxZoom: 13, duration: 0 })
  }
}
function setCursor() { if (map) map.getCanvas().style.cursor = props.selecting ? 'crosshair' : '' }
onMounted(() => {
  if (!root.value) return
  map = new maplibregl.Map({ container: root.value, style: 'https://tiles.openfreemap.org/styles/liberty', center: [32.548, 50.26], zoom: 12, attributionControl: { compact: true } })
  map.addControl(new maplibregl.NavigationControl(), 'top-right')
  map.on('error', () => emit('status', 'Карта тимчасово недоступна. Синтетичної підміни немає.'))
  map.on('load', () => {
    map!.addSource('route-plans', { type: 'geojson', data: featureCollection() as any })
    map!.addLayer({ id: 'route-lines', type: 'line', source: 'route-plans', filter: ['!', ['in', ['get', 'kind'], ['literal', ['analysis_transect', 'terrain_candidate']]]], paint: { 'line-color': '#68717d', 'line-width': 5, 'line-opacity': .82 } })
    map!.addLayer({ id: 'analysis-lines', type: 'line', source: 'route-plans', filter: ['in', ['get', 'kind'], ['literal', ['analysis_transect', 'terrain_candidate']]], paint: { 'line-color': '#697586', 'line-width': 4, 'line-dasharray': [2, 2] } })
    map!.addLayer({ id: 'route-selected', type: 'line', source: 'route-plans', filter: ['==', ['get', 'id'], ''], paint: { 'line-color': '#1468f4', 'line-width': 7 } })
    map!.addLayer({ id: 'candidate-selected', type: 'line', source: 'route-plans', filter: ['==', ['get', 'id'], ''], paint: { 'line-color': '#1468f4', 'line-width': 7, 'line-dasharray': [2, 2] } })
    map!.addSource('land-cover-trace', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } })
    map!.addLayer({ id: 'land-cover-known', type: 'line', source: 'land-cover-trace', filter: ['==', ['get', 'unknown'], false], paint: { 'line-color': ['get', 'color'], 'line-width': 9, 'line-opacity': .84 } }, 'analysis-lines')
    map!.addLayer({ id: 'land-cover-unknown', type: 'line', source: 'land-cover-trace', filter: ['==', ['get', 'unknown'], true], paint: { 'line-color': '#8a929e', 'line-width': 9, 'line-opacity': .84, 'line-dasharray': [1, 1] } }, 'analysis-lines')
    map!.addSource('inspection-section', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } })
    map!.addLayer({ id: 'inspection-line', type: 'line', source: 'inspection-section', filter: ['==', ['geometry-type'], 'LineString'], paint: { 'line-color': '#1468f4', 'line-width': 16, 'line-opacity': .3 } })
    map!.addLayer({ id: 'inspection-point', type: 'circle', source: 'inspection-section', filter: ['==', ['geometry-type'], 'Point'], paint: { 'circle-radius': 7, 'circle-color': '#1468f4', 'circle-stroke-color': '#ffffff', 'circle-stroke-width': 3 } })
    map!.addSource('inspectable-sections', { type: 'geojson', data: sectionFeatureCollection() as any })
    map!.addLayer({ id: 'section-hit', type: 'line', source: 'inspectable-sections', paint: { 'line-color': '#ffffff', 'line-width': 24, 'line-opacity': 0 } })
    map!.addSource('section-preview', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } })
    map!.addLayer({ id: 'section-preview-line', type: 'line', source: 'section-preview', paint: { 'line-color': '#1468f4', 'line-width': 12, 'line-opacity': .22 } })

    map!.on('click', event => { if (props.selecting) emit('point', { longitude: event.lngLat.lng, latitude: event.lngLat.lat, label: props.selecting === 'origin' ? 'Точка A' : 'Точка B' }) })
    map!.on('click', 'route-lines', event => { const id = event.features?.[0]?.properties?.id; if (id && !props.selecting && !map!.queryRenderedFeatures(event.point, { layers: ['section-hit'] }).length) emit('route', id) })
    map!.on('click', 'analysis-lines', event => { const id = event.features?.[0]?.properties?.id; if (id && !props.selecting && !map!.queryRenderedFeatures(event.point, { layers: ['section-hit'] }).length && !emitLineSelection(event)) emit('route', id) })
    map!.on('click', 'section-hit', event => { const index = Number(event.features?.[0]?.properties?.index); if (Number.isInteger(index) && !emitLineSelection(event)) emitSection(index) })
    map!.on('mousemove', 'section-hit', event => { const index = Number(event.features?.[0]?.properties?.index); if (Number.isInteger(index)) emitPreview(index); if (!props.selecting) map!.getCanvas().style.cursor = 'pointer' })
    map!.on('mouseleave', 'section-hit', () => { emitPreview(null); setCursor() })
    map!.on('mouseenter', 'route-lines', () => { if (map) map.getCanvas().style.cursor = 'pointer' })
    map!.on('mouseleave', 'route-lines', setCursor)
    ready = true; update(); updateLandCover(); updateSection(); updateSectionControls(); setCursor(); emit('status', '')
  })
  window.addEventListener('resize', resizeMap)
})
function resizeMap() { map?.resize(); update() }
watch(() => [props.origin, props.destination, props.routes, props.selectedRouteId, props.inspecting], update, { deep: true })
watch(() => props.selecting, setCursor)
watch(() => [props.landCoverTrace, showLandCover.value], updateLandCover, { deep: true })
watch(() => [props.inspectedSection, props.inspectionPoint], updateSection, { deep: true })
watch(() => [props.sections, props.selectedSectionIndex, props.previewSectionIndex, props.inspecting, props.selecting, props.selectedRouteId], () => { updateSectionControls(); updateSection() }, { deep: true })
onBeforeUnmount(() => { window.removeEventListener('resize', resizeMap); endpointMarkers.forEach(marker => marker.remove()); sectionMarkers.forEach(marker => marker.remove()); sectionMarkers.clear(); map?.remove() })
</script>

<template><div class="route-map-wrap"><div ref="root" class="route-map" aria-label="Інтерактивна карта маршруту"></div><div v-if="landCoverTrace" class="land-cover-control"><button type="button" aria-label="Покрив · 2021" :aria-pressed="showLandCover" @click="showLandCover = !showLandCover">Покрив · 2021</button><template v-if="showLandCover"><p>Лише лінія · не коридор<br>Вода й болота — класи 2021, не поточне затоплення.</p><ul class="land-cover-legend" aria-label="Класи покриву 2021"><li v-for="item in landCoverLegend" :key="item.code ?? 'unknown'"><i :class="{ unknown: item.code === null }" :style="{ backgroundColor: item.color }"></i>{{ item.label }}</li></ul></template></div></div></template>

<style>
.route-map .route-section-marker{width:28px;height:28px;border:2px solid #fff;border-radius:8px;background:#fff;color:var(--blue);box-shadow:0 0 0 1px #1468f4,0 2px 5px #14203330;font:800 12px Manrope,Inter,system-ui,sans-serif;line-height:24px;text-align:center;padding:0;cursor:pointer}
.route-map-wrap{position:relative;width:100%;height:100%}.route-map{width:100%;height:100%}.land-cover-control{position:absolute;left:12px;bottom:24px;z-index:2;max-width:230px}.land-cover-control button{border:1px solid #c9d0d9;border-radius:6px;background:#fff;color:#172033;padding:7px 9px;font:700 11px Manrope,Inter,system-ui,sans-serif;box-shadow:0 1px 4px #14203320}.land-cover-control button[aria-pressed=true]{border-color:#1468f4;color:#0f55c5}.land-cover-control p{margin:5px 0 0;padding:6px 8px;border-radius:5px;background:#fffffff0;color:#4a5564;font:10px/1.4 Manrope,Inter,system-ui,sans-serif;box-shadow:0 1px 4px #14203320}
.route-map .route-section-marker[aria-pressed=true]{background:var(--blue);color:#fff}.route-map .route-section-marker:hover{box-shadow:0 0 0 2px #1468f4,0 2px 6px #14203340}.route-map .route-section-marker:focus-visible{outline:3px solid #1468f4;outline-offset:4px}
.land-cover-control{top:12px;bottom:auto}.land-cover-control button{min-height:36px}.land-cover-legend{list-style:none;margin:0;padding:7px 8px;background:#fffffff0;border-radius:5px;display:flex;flex-wrap:wrap;gap:5px 10px;font-size:10px}.land-cover-legend li{display:flex;align-items:center;gap:5px}.land-cover-legend i{display:block;width:14px;height:5px}.land-cover-legend i.unknown{background-image:repeating-linear-gradient(135deg,#8a929e 0 2px,#d8dee7 2px 4px)}
@media(max-width:700px){.route-map .route-section-marker{width:34px;height:34px;line-height:30px;font-size:13px}.land-cover-control{max-width:180px}}
</style>
