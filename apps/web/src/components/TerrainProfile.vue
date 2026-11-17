<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { ApiError } from '../lib/api'
import type { RouteApiClient } from '../lib/routeTypes'
import type { TerrainProfilePoint, TerrainProfileResponse } from '../lib/terrainProfileTypes'
import { coverClassification, validateLandCoverTrace, type LandCoverTrace } from '../lib/landCoverTraceTypes'
import SurfaceProfile from './SurfaceProfile.vue'
import { pointAtChainage, segmentLength } from '../lib/transectSelection'
import type { RouteGeometry } from '../lib/routeTypes'
import type { SurfaceProfileSource } from '../lib/surfaceProfileTypes'

const props = defineProps<{ client: RouteApiClient; planId: string; routeId: string; tripDate: string; routeGeometry?: RouteGeometry; inspectionReady?: boolean }>()
const emit = defineEmits<{ refresh: []; trace: [trace: LandCoverTrace | null]; 'inspect-point': [chainage: number] }>()
const result = ref<TerrainProfileResponse | null>(null), busy = ref(false), error = ref('')
const expired = ref(false)
let revision = 0
function classification(point: TerrainProfilePoint) { return coverClassification(point.land_cover_class) }
function number(value: number, digits = 0) { return value.toFixed(digits).replace('.', ',') }
const heights = computed(() => (result.value?.points || []).filter(point => typeof point.elevation_m === 'number' && Number.isFinite(point.elevation_m)))
const bounds = computed(() => { const values = heights.value.map(point => point.elevation_m as number); return values.length ? [Math.min(...values), Math.max(...values)] : null })
function x(point: TerrainProfilePoint) { return 38 + point.chainage_m / result.value!.distance_m * 274 }
function y(point: TerrainProfilePoint) { const [low, high] = bounds.value!; return 87 - ((point.elevation_m! - low) / Math.max(1, high - low)) * 67 }
const trace = computed(() => {
  let previousValid = false
  return (result.value?.points || []).map(point => {
    if (point.elevation_m === null || !Number.isFinite(point.elevation_m)) { previousValid = false; return '' }
    const command = previousValid ? 'L' : 'M'; previousValid = true
    return `${command}${x(point).toFixed(2)},${y(point).toFixed(2)}`
  }).join(' ')
})
const coverCount = computed(() => (result.value?.points || []).filter(point => point.land_cover_class !== null && coverClassification(point.land_cover_class).label !== 'Покрив невідомий').length)
const legend = computed(() => [...new Map((result.value?.points || []).map(point => { const item = classification(point); return [item.label, item] })).values()])
const coverTrace = computed(() => {
  const data = result.value
  return data?.land_cover_trace ? validateLandCoverTrace(data.land_cover_trace, { distance_m: data.distance_m, origin: data.points[0].point, destination: data.points[data.points.length - 1].point }) : null
})
const surfaceSource = computed<SurfaceProfileSource | null>(() => {
  const source = (result.value?.sources || []).find(item => item.id === 'sentinel-2-l2a' && item.extraction_scope === 'spaced_scene_classification_points')
  return source ? source as SurfaceProfileSource : null
})
const profileGeometryAgrees = computed(() => {
  const geometry = props.routeGeometry, data = result.value
  if (!geometry || geometry.type !== 'LineString' || !Array.isArray(geometry.coordinates) || !data?.points.length || !pointAtChainage(geometry.coordinates, 0)) return false
  const total = geometry.coordinates.slice(1).reduce((sum, point, index) => sum + segmentLength(geometry.coordinates[index], point), 0)
  if (Math.abs(total - data.distance_m) > .01 || data.points[0].chainage_m !== 0 || Math.abs(data.points.at(-1)!.chainage_m - total) > .01) return false
  return data.points.every((profilePoint, index) => {
    if (index && profilePoint.chainage_m <= data.points[index - 1].chainage_m) return false
    const expected = pointAtChainage(geometry.coordinates, profilePoint.chainage_m)
    return !!expected && Math.abs(expected.latitude - profilePoint.point.latitude) <= 1e-8 && Math.abs(expected.longitude - profilePoint.point.longitude) <= 1e-8
  })
})
const surfaceInspectionReady = computed(() => !!props.inspectionReady && profileGeometryAgrees.value)
function inspectTerrainPoint(point: TerrainProfilePoint) {
  if (surfaceInspectionReady.value && result.value?.points.includes(point)) emit('inspect-point', point.chainage_m)
}
function inspectGraph(event: MouseEvent) {
  if (!surfaceInspectionReady.value || !result.value || event.button !== 0 || !(event.currentTarget instanceof SVGSVGElement)) return
  const box = event.currentTarget.getBoundingClientRect()
  if (!(box.width > 0 && box.height > 0)) return
  const plotX = (event.clientX - box.left) / box.width * 320, plotY = (event.clientY - box.top) / box.height * 133
  if (!Number.isFinite(plotX) || !Number.isFinite(plotY) || plotX < 38 || plotX > 312 || plotY < 10 || plotY > 112) return
  const chainage = (plotX - 38) / 274 * result.value.distance_m
  const closest = result.value.points.reduce((a, b) => Math.abs(a.chainage_m - chainage) <= Math.abs(b.chainage_m - chainage) ? a : b)
  inspectTerrainPoint(closest)
}
async function load() {
  const requestRevision = ++revision
  busy.value = true; result.value = null; error.value = ''; expired.value = false; emit('trace', null)
  try {
    const data = await props.client.post<TerrainProfileResponse>('/terrain-profile', { plan_id: props.planId, route_id: props.routeId })
    if (requestRevision !== revision) return
    if (data.plan_id !== props.planId || data.route_id !== props.routeId || data.trip_date !== props.tripDate || data.coverage !== 'not_continuous' || data.evidence_scope !== 'spaced_point_samples' || data.synthetic !== false || !Array.isArray(data.points) || data.points.length < 2 || data.points.length > 81 || !Number.isFinite(data.distance_m) || data.distance_m <= 0 || !Number.isFinite(data.sample_spacing_m) || data.sample_spacing_m <= 0 || data.sample_spacing_m > 250.01) throw new Error('Profile binding or sampling mismatch')
    if (!data.points.every(point => Number.isFinite(point.chainage_m) && point.chainage_m >= 0 && point.chainage_m <= data.distance_m + .01 && Number.isFinite(point.point?.longitude) && Number.isFinite(point.point?.latitude) && point.point.longitude >= -180 && point.point.longitude <= 180 && point.point.latitude >= -90 && point.point.latitude <= 90 && (point.elevation_m === null || typeof point.elevation_m === 'number' && Number.isFinite(point.elevation_m)))) throw new Error('Invalid profile points')
    result.value = data
    emit('trace', coverTrace.value)
  } catch (cause) {
    if (requestRevision === revision) {
      expired.value = cause instanceof ApiError && cause.status === 404
      error.value = expired.value ? 'Строк дії плану минув. Потрібен новий аналіз.' : 'Не вдалося отримати огляд. Дані обраної ділянки доступні окремо.'
      emit('trace', null)
    }
  }
  finally { if (requestRevision === revision) busy.value = false }
}
watch(() => [props.planId, props.routeId, props.tripDate], load, { immediate: true, flush: 'sync' })
onBeforeUnmount(() => { revision++; emit('trace', null) })
</script>

<template>
  <section class="terrain-profile" aria-label="Огляд висоти та покриву вздовж лінії">
    <header><h3>Висота вздовж A → B</h3><span>DSM · м</span></header>
    <p v-if="busy" role="status">Читаємо висоти й покрив вздовж лінії…</p>
    <div v-else-if="error" role="alert"><p>{{ error }}</p><button class="profile-retry" type="button" @click="expired ? emit('refresh') : load()">{{ expired ? 'Оновити аналіз' : 'Повторити огляд' }}</button></div>
    <template v-else-if="result">
      <svg viewBox="0 0 320 133" role="img" aria-label="Точковий профіль висоти DSM і земного покриву" :class="{ 'profile-selectable': surfaceInspectionReady }" @click="inspectGraph">
        <line x1="38" y1="20" x2="312" y2="20" class="profile-grid" /><line x1="38" y1="87" x2="312" y2="87" class="profile-grid" />
        <text v-if="bounds" x="0" y="23">{{ number(bounds[1]) }}</text><text v-if="bounds" x="0" y="90">{{ number(bounds[0]) }}</text>
        <path v-if="bounds" class="profile-trace" :d="trace" />
        <circle v-for="point in heights" :key="point.chainage_m" class="profile-height-point" :cx="x(point)" :cy="y(point)" r="2.7"><title>{{ number(point.chainage_m) }} м · DSM {{ number(point.elevation_m!, 1) }} м</title></circle>
        <circle v-for="point in result.points" :key="point.chainage_m" class="profile-cover-point" :cx="x(point)" cy="105" r="3.3" :fill="classification(point).color"><title>{{ number(point.chainage_m) }} м · {{ classification(point).label }} · ESA 2021</title></circle>
        <text x="38" y="130">A · 0 км</text><text x="312" y="130" text-anchor="end">B · {{ number(result.distance_m / 1000, 2) }} км</text>
      </svg>
      <p class="profile-counts">Висота: {{ heights.length }} / {{ result.points.length }} точок · Покрив: {{ coverCount }} / {{ result.points.length }}</p>
      <section v-if="coverTrace" class="trace-summary" aria-label="Покрив уздовж лінії">
        <strong>Покрив уздовж лінії · ESA 2021</strong><span>{{ coverTrace.known_m.toFixed(0).replace('.', ',') }} м відомо · {{ coverTrace.unknown_m.toFixed(0).replace('.', ',') }} м невідомо</span>
        <div><i v-for="segment in coverTrace.segments" :key="`${segment.start_m}-${segment.end_m}`" :class="{ unknown: segment.class_code === null }" :style="{ flex: segment.end_m - segment.start_m, backgroundColor: coverClassification(segment.class_code).color }"></i></div>
      </section>
      <p v-if="!heights.length" class="profile-note">Висоти не отримано; відсутність даних не означає рівну поверхню.</p>
      <button v-if="result.status === 'unavailable'" type="button" class="profile-retry" @click="load()">Повторити огляд</button>
      <div class="profile-legend"><span v-for="item in legend" :key="item.label"><i :style="{ backgroundColor: item.color }"></i>{{ item.label }}</span></div>
      <p class="profile-note">Крок {{ number(result.sample_spacing_m) }} м · Покрив ESA 2021.<br>Точкова вибірка, не суцільне покриття. DSM включає рослинність і споруди.<template v-if="surfaceInspectionReady"><br>Натисніть графік, щоб відкрити найближчу точку вибірки. Усі точки — у таблиці нижче.</template></p>
      <SurfaceProfile :summary="result.surface_observation_profile" :source="surfaceSource" :profile-points="result.points" :trip-date="tripDate" :inspection-ready="surfaceInspectionReady" @inspect-point="emit('inspect-point', $event)" />
      <details class="profile-evidence"><summary>Вибірка та джерела</summary>
        <table><thead><tr><th scope="col">Від A</th><th scope="col">DSM, м</th><th scope="col">Покрив 2021</th></tr></thead><tbody><tr v-for="point in result.points" :key="point.chainage_m"><td><button v-if="surfaceInspectionReady" type="button" class="profile-inspect" data-testid="terrain-inspect" :aria-label="`Відкрити точку ${number(point.chainage_m)} м від A`" @click="inspectTerrainPoint(point)">{{ number(point.chainage_m) }} м</button><template v-else>{{ number(point.chainage_m) }} м</template></td><td>{{ point.elevation_m === null ? '—' : number(point.elevation_m, 1) }}</td><td>{{ classification(point).label }}</td></tr></tbody></table>
        <p v-for="source in result.sources || []" :key="source.id" class="profile-provenance">{{ source.product || source.id }}<small>{{ source.status || 'Невідомо' }} · {{ source.retrieved_at || 'Час отримання невідомий' }}</small><code v-if="source.content_sha256">{{ source.content_sha256 }}</code></p>
        <p v-for="warning in result.warnings_uk || []" :key="warning">{{ warning }}</p>
      </details>
    </template>
  </section>
</template>

<style scoped>
.terrain-profile{padding:16px;border-bottom:1px solid var(--line);background:#fff}.terrain-profile header{display:flex;justify-content:space-between;align-items:center;gap:8px}.terrain-profile h3{margin:0;font-size:13px}.terrain-profile header span{font-size:10px;color:var(--muted);white-space:nowrap}.terrain-profile svg{width:100%;height:auto;display:block;margin:10px 0 4px}.terrain-profile svg text{font-family:inherit;font-size:9px;fill:var(--muted)}.profile-grid{stroke:var(--line);stroke-width:1}.profile-trace{stroke:var(--blue);stroke-width:1.5;stroke-dasharray:3 2;fill:none}.profile-height-point{fill:var(--blue)}.profile-counts,.profile-note,.terrain-profile>p{font-size:10px;line-height:1.5;color:var(--muted)}.profile-legend{display:flex;flex-wrap:wrap;gap:5px 12px;margin:7px 0}.profile-legend span{display:inline-flex;align-items:center;gap:4px;font-size:10px;color:var(--muted)}.profile-legend i{width:7px;height:7px;border-radius:50%}.profile-note{margin-top:7px}
.profile-evidence{font-size:10px;margin-top:9px;color:var(--muted)}.profile-evidence summary{color:var(--blue);cursor:pointer}.profile-evidence table{width:100%;table-layout:fixed;border-collapse:collapse;margin:8px 0}.profile-evidence th,.profile-evidence td{text-align:left;vertical-align:top;padding:5px 3px;border-bottom:1px solid var(--line);overflow-wrap:anywhere}.profile-evidence th:first-child{width:22%}.profile-evidence th:nth-child(2){width:23%}.profile-evidence p{margin-top:9px;font-size:10px;line-height:1.45}.profile-provenance small,.profile-provenance code{display:block;font-size:9px;overflow-wrap:anywhere;margin-top:4px}.profile-retry{border:1px solid var(--line);background:#fff;color:var(--blue);border-radius:5px;padding:7px 10px;font-size:11px;margin-top:9px}
.trace-summary{margin:9px 0;font-size:10px;color:var(--muted)}.trace-summary strong,.trace-summary span{display:block}.trace-summary span{margin-top:2px}.trace-summary div{height:7px;display:flex;margin-top:5px;border-radius:3px;overflow:hidden;background:#d8dee7}.trace-summary i.unknown{background-image:repeating-linear-gradient(135deg,#8a929e 0 2px,#d8dee7 2px 4px)!important}
.profile-inspect{border:0;background:transparent;color:var(--blue);font:inherit;text-decoration:underline;padding:2px 0;min-height:24px;cursor:pointer}.profile-inspect:focus-visible{outline:2px solid var(--blue);outline-offset:2px;border-radius:2px}
.terrain-profile svg.profile-selectable{cursor:crosshair}
</style>
