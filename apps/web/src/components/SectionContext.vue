<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { ApiError } from '../lib/api'
import SurfaceObservation from './SurfaceObservation.vue'
import WeatherDayConditions from './WeatherDayConditions.vue'
import ReferenceSoilType from './ReferenceSoilType.vue'
import type { RouteApiClient, RouteGeometry, RouteRequest, VehicleKind } from '../lib/routeTypes'
import { isTerrainAnalysis } from '../lib/routeTypes'
import type { ContextSource, RouteSection, SectionContextResponse } from '../lib/sectionContextTypes'
import { pointAtChainage, sectionForChainage } from '../lib/transectSelection'

const props = defineProps<{ client: RouteApiClient; planId: string; routeId: string; tripDate: string; routeGeometry?: RouteGeometry; selectedSectionIndex?: number; selectedChainage?: number | null; analysisKind?: string; vehicle?: RouteRequest['vehicle'] }>()
const emit = defineEmits<{ section: [section: RouteSection | null]; samplePoint: [point: { longitude: number; latitude: number } | null]; sections: [sections: RouteSection[]]; selectSection: [index: number]; selectChainage: [chainage: number | null]; previewSection: [index: number | null]; refresh: [] }>()
const index = ref(0), busy = ref(false), error = ref('')
const expired = ref(false)
const result = ref<SectionContextResponse | null>(null), sections = ref<RouteSection[]>([])
const draftChainage = ref(0)
let revision = 0
const tripFocused = computed(() => isTerrainAnalysis(props.analysisKind))
const vehicleNames: Record<VehicleKind, string> = { car: 'Легковий автомобіль', truck_4x4: 'Вантажівка 4×4', truck_6x6: 'Вантажівка 6×6' }
const vehicleSummary = computed(() => {
  const vehicle = props.vehicle
  if (!vehicle || !Object.hasOwn(vehicleNames, vehicle.kind) || typeof vehicle.gross_mass_t !== 'number' || !Number.isFinite(vehicle.gross_mass_t) || vehicle.gross_mass_t <= 0) return 'Параметри транспорту недоступні'
  return `${vehicleNames[vehicle.kind]} · ${String(vehicle.gross_mass_t).replace('.', ',')} т`
})
const labels: Record<string, string> = { tree_cover: 'Дерева', shrubland: 'Чагарники', grassland: 'Трав’яний покрив', cropland: 'Рілля', built_up: 'Забудова', bare_sparse_vegetation: 'Розріджена рослинність', snow_ice: 'Сніг / лід', permanent_water: 'Постійні водойми', herbaceous_wetland: 'Водно-болотні угіддя', mangroves: 'Мангри', moss_lichen: 'Мохи та лишайники' }
const landCover = computed(() => labels[result.value?.land_cover?.label || ''] || 'Немає даних')
const soil = computed(() => result.value?.ground_composition?.composition)
const selectedPoint = computed(() => result.value?.sample_selection?.point || result.value?.sections.find(section => section.index === index.value)?.point)
const selectedRange = computed(() => sections.value.find(section => section.index === index.value))
const exactSelection = computed(() => Number.isFinite(props.selectedChainage) ? props.selectedChainage! : null)
const hasSoil = computed(() => Object.values(soil.value || {}).some(value => typeof value === 'number' && Number.isFinite(value)))
const sources = computed<ContextSource[]>(() => {
  const rows = [...(result.value?.sources || []), ...(result.value?.weather?.source ? [result.value.weather.source] : [])]
  return [...new Map(rows.map(row => [`${row.id}:${row.extraction_scope || 'point'}`, row])).values()]
})
function number(value: unknown, decimals: number) { return typeof value === 'number' && Number.isFinite(value) ? value.toFixed(decimals).replace('.', ',') : '—' }
function range(field: string, unit: string, decimals: number) {
  const weather = result.value?.weather
  if (weather?.assessment_date !== props.tripDate || weather.units?.[field] !== unit) return '—'
  const values = (weather.series || []).filter(row => row.time.startsWith(`${props.tripDate}T`)).map(row => row[field]).filter((value): value is number => typeof value === 'number' && Number.isFinite(value))
  if (!values.length) return '—'
  return `${number(Math.min(...values), decimals)}–${number(Math.max(...values), decimals)}`
}
function chainage(section: RouteSection) { return `${number(section.from_m, 0)}–${number(section.to_m, 0)} м` }
function samePoint(a: { longitude: number; latitude: number }, b: { longitude: number; latitude: number }) { return Math.abs(a.longitude - b.longitude) < 1e-6 && Math.abs(a.latitude - b.latitude) < 1e-6 }
function validSelection(data: SectionContextResponse, requested: number | null, sectionIndex: number) {
  if (requested === null) return !data.sample_selection
  const selection = data.sample_selection, section = sectionForChainage(data.sections, requested, sectionIndex)
  if (!tripFocused.value || props.routeGeometry?.type !== 'LineString' || !selection || selection.kind !== 'line_chainage' || !section || section.index !== sectionIndex || selection.chainage_m !== requested || !Number.isFinite(selection.point.longitude) || !Number.isFinite(selection.point.latitude)) return false
  const expected = pointAtChainage(props.routeGeometry.coordinates, requested)
  return !!expected && samePoint(selection.point, expected)
}
async function load(sectionIndex = index.value, chainage = exactSelection.value) {
  const requestRevision = ++revision
  index.value = sectionIndex; busy.value = true; error.value = ''; expired.value = false; result.value = null; emit('section', null); emit('samplePoint', null)
  try {
    const body = chainage === null ? { plan_id: props.planId, route_id: props.routeId, section_index: sectionIndex } : { plan_id: props.planId, route_id: props.routeId, section_index: sectionIndex, sample_chainage_m: chainage }
    const data = await props.client.post<SectionContextResponse>('/route-context', body)
    if (requestRevision !== revision) return
    if (data.plan_id !== props.planId || data.route_id !== props.routeId || data.trip_date !== props.tripDate || data.section_index !== sectionIndex || !Array.isArray(data.sections) || !validSelection(data, chainage, sectionIndex)) throw new Error('Context binding mismatch')
    result.value = data; sections.value = data.sections; emit('sections', data.sections); emit('section', data.sections.find(section => section.index === sectionIndex) || null); emit('samplePoint', data.sample_selection?.point || data.sections.find(section => section.index === sectionIndex)?.point || null)
    const selected = data.sections.find(section => section.index === sectionIndex)
    if (selected) draftChainage.value = data.sample_selection?.chainage_m ?? (selected.from_m + selected.to_m) / 2
  } catch (cause) {
    if (requestRevision === revision) {
      expired.value = cause instanceof ApiError && cause.status === 404
      error.value = expired.value ? 'Строк дії плану минув. Потрібен новий аналіз.' : 'Не вдалося завантажити дані ділянки. Введені точки збережено.'
    }
  }
  finally { if (requestRevision === revision) busy.value = false }
}
function chooseSection(n: number) {
  if (!sections.value.some(section => section.index === n)) return
  emit('selectChainage', null); emit('selectSection', n); emit('previewSection', null)
  if (props.selectedSectionIndex === undefined) load(n)
}
function commitChainage() { const section = selectedRange.value, value = draftChainage.value; if (section && Number.isFinite(value) && value >= section.from_m && value <= section.to_m) emit('selectChainage', value) }
watch(() => [props.planId, props.routeId, props.tripDate, props.selectedSectionIndex, props.selectedChainage], (current, previous) => {
  if (!previous || current.slice(0, 3).some((value, i) => value !== previous[i])) {
    index.value = 0; sections.value = []; emit('sections', [])
  }
  const selected = props.selectedSectionIndex ?? index.value
  const chainage = Number.isFinite(props.selectedChainage) ? props.selectedChainage! : null
  if (chainage !== null) draftChainage.value = chainage
  load(Number.isInteger(selected) && selected >= 0 && selected < 32 ? selected : 0)
}, { immediate: true, flush: 'pre' })
onBeforeUnmount(() => { revision++; emit('section', null); emit('samplePoint', null); emit('previewSection', null) })
</script>

<template>
  <section class="section-context" aria-label="Дані обраної ділянки">
    <h3>Дані ділянки</h3>
    <div class="section-options" aria-label="Оберіть ділянку">
      <button v-for="section in sections" :key="section.index" type="button" class="section-option" :data-section-index="section.index" :aria-pressed="index === section.index" @click="chooseSection(section.index)" @mouseenter="emit('previewSection', section.index)" @mouseleave="emit('previewSection', null)" @focus="emit('previewSection', section.index)" @blur="emit('previewSection', null)">Ділянка {{ section.index + 1 }}<small>{{ chainage(section) }}</small><span v-if="section.label_uk" class="section-basis">{{ section.label_uk }}</span></button>
    </div>
    <p v-if="sections.some(section => section.basis === 'sampled_search_grid')" class="sample-note">{{ sections.length }} ділянок · за змінами покриву 2021 і перепадами DSM вздовж цього шляху. Межі наближені до сітки, не оцінка проїзності.<template v-if="sections.some(section => section.generalized)"> Дрібні зміни згруповано; змішані класи збережено.</template></p>
    <p class="sample-note">{{ tripFocused ? 'Одна точка, не суцільна оцінка ділянки.' : 'Оберіть ділянку на карті або тут. Вибірка в одній точці, не суцільна оцінка ділянки.' }}</p>
    <details v-if="tripFocused && selectedRange" class="position-picker"><summary>{{ result?.sample_selection ? `${number(result.sample_selection.chainage_m, 0)} м від A · змінити точку` : 'Точка на лінії' }}</summary><form @submit.prevent="commitChainage"><label>Від A: {{ number(draftChainage, 0) }} м<input data-testid="sample-chainage" v-model.number="draftChainage" type="range" :min="selectedRange.from_m" :max="selectedRange.to_m" step="1" aria-label="Відстань від точки A, метри"></label><button data-testid="commit-sample-chainage" type="submit">Перевірити точку</button></form><p>Оберіть точку на карті або тут. Одна точка на лінії, не коридор і не точність джерел.</p></details>
    <p v-if="busy" role="status">Завантажуємо місцевість і прогноз…</p>
    <div v-else-if="error" role="alert"><p>{{ error }}</p><button class="context-retry" type="button" @click="expired ? emit('refresh') : load()">{{ expired ? 'Оновити аналіз' : 'Повторити' }}</button></div>
    <template v-else-if="result">
      <section v-if="tripFocused" class="trip-request" aria-label="Параметри та обмеження поїздки">
        <strong>{{ vehicleSummary }}</strong><small>{{ tripDate }} · UTC · запит поїздки</small>
        <p>Проїзність не оцінено.</p><p>Поточне підтоплення та просвіти для техніки невідомі.</p>
      </section>
      <WeatherDayConditions v-if="tripFocused && result.weather?.day_summary" :summary="result.weather.day_summary" :trip-date="tripDate" :antecedent="result.weather.antecedent_precipitation" :outlook="result.weather.outlook" :soil-water="result.weather.soil_water" show-soil-water :selected-point="selectedPoint" :source-digest="result.weather.source?.content_sha256" />
      <p v-if="tripFocused && result.weather?.status === 'date_out_of_range'" class="context-gap">Дата поза горизонтом прогнозу. Іншу дату не підставлено.</p>
      <SurfaceObservation v-if="tripFocused && selectedPoint && 'surface_observation' in result" :observation="result.surface_observation" :selected-point="selectedPoint" :trip-date="tripDate" />
      <component :is="tripFocused ? 'details' : 'div'" :class="{ 'terrain-details': tripFocused }">
      <summary v-if="tripFocused">Місцевість · ґрунт, рельєф, ліс</summary>
      <dl class="context-metrics">
        <div><dt>Земний покрив</dt><dd>{{ landCover }}</dd><small>ESA {{ result.land_cover?.reference_year || '—' }} · {{ result.land_cover?.support_m ?? '—' }} м</small></div>
        <div><dt>Висота поверхні DSM</dt><dd>{{ number(result.terrain?.elevation_m, 1) }} м</dd><small>Комірка {{ result.terrain?.support_m ?? '—' }} м</small></div>
        <div v-if="!tripFocused"><dt>Вологість 0–1 см</dt><dd>{{ range('soil_moisture_0_to_1cm', 'm³/m³', 3) }}</dd><small>м³/м³ · модельна комірка</small></div>
        <div><dt>Температура повітря</dt><dd>{{ range('temperature_2m', '°C', 1) }} °C</dd><small>{{ tripDate }} · UTC</small></div>
        <div v-if="result.local_terrain"><dt>Схил поверхні DSM</dt><dd>{{ number(result.local_terrain.slope_deg, 1) }}°</dd><small>Локальна поверхня, не ухил дороги</small></div>
        <div v-if="result.vegetation"><dt>Лісистість околиці</dt><dd>{{ number(result.vegetation.tree_cover_percent, 1) }}%</dd><small>Клас «дерева» · {{ result.vegetation.reference_year || '—' }}<br>Околиця ≈ {{ number(result.vegetation.footprint_m?.width, 0) }} × {{ number(result.vegetation.footprint_m?.height, 0) }} м<br>Відомі комірки: {{ number(result.vegetation.valid_fraction == null ? null : result.vegetation.valid_fraction * 100, 0) }}%</small></div>
        <div v-if="result.canopy_cover" class="canopy-metric"><dt>Зімкнутість крон</dt><dd>{{ number(result.canopy_cover.percent, 1) }}{{ result.canopy_cover.percent == null ? '' : '%' }}</dd><small>Copernicus TCD {{ result.canopy_cover.reference_year }} · {{ result.canopy_cover.resolution_m }} м<br>Історична комірка, не поточне спостереження</small></div>
      </dl>
      <SurfaceObservation v-if="!tripFocused && selectedPoint && 'surface_observation' in result" :observation="result.surface_observation" :selected-point="selectedPoint" :trip-date="tripDate" />
      <WeatherDayConditions v-if="!tripFocused && result.weather?.day_summary" :summary="result.weather.day_summary" :trip-date="tripDate" :antecedent="result.weather.antecedent_precipitation" />
      <p v-if="!tripFocused && result.weather?.status === 'date_out_of_range'" class="context-gap">Дата поза горизонтом прогнозу. Іншу дату не підставлено.</p>
      <div v-if="hasSoil" class="soil-composition"><h4>Природний ґрунт</h4><p>Пісок: {{ number(soil?.sand, 1) }}% · Пил: {{ number(soil?.silt, 1) }}% · Глина: {{ number(soil?.clay, 1) }}%</p><small>{{ result.ground_composition?.composition_depth_cm?.join('–') }} см · {{ result.ground_composition?.support_m }} м. Сума оцінок: {{ number(result.ground_composition?.closure?.total_percent, 1) }}%. Незалежні оцінки без нормалізації; не польова проба. Інтервали невизначеності не отримано.</small></div>
      <p v-else class="context-gap">Склад ґрунту не отримано. Не підмінюємо його типом рослинності.</p>
      <ReferenceSoilType v-if="tripFocused && selectedPoint && 'soil_type' in result" :soil-type="result.soil_type" :selected-point="selectedPoint" />
      <p v-if="!tripFocused" class="context-gap">Проїзність не оцінено.</p>
      <p v-if="result.vegetation" class="sample-note">Лісистість — частка комірок з класом «дерева», не щільність стовбурів. Просвіти для техніки невідомі. <template v-if="result.canopy_cover?.percent == null">Зімкнутість крон невідома.</template></p>
      <p v-if="result.local_terrain" class="sample-note">DSM включає дерева й будівлі, тому не дорівнює рельєфу голої землі.</p>
      <p class="sample-note">Покрив 2021 року не показує поточне підтоплення. Вологість погодної моделі не є вимірюванням дороги.</p>
      </component>
      <details class="context-sources"><summary>Джерела та обмеження</summary><p v-for="source in sources" :key="`${source.id}:${source.extraction_scope || 'point'}`">{{ source.product || source.name || source.id }}{{ source.extraction_scope === 'local_window' ? ' · локальний окіл' : '' }}<small>{{ source.status || 'Модельні дані' }} · {{ source.retrieved_at || 'Час отримання невідомий' }}</small><code v-if="source.content_sha256">{{ source.content_sha256 }}</code></p><p v-for="warning in result.warnings_uk" :key="warning">{{ warning }}</p></details>
    </template>
  </section>
</template>

<style scoped>
.section-context .section-options{grid-template-columns:repeat(auto-fit,minmax(120px,1fr));max-height:210px;overflow-y:auto}.section-basis{display:block;margin-top:5px;font-size:9px;line-height:1.4;color:var(--muted)}
.trip-request{margin:10px 0;padding:10px;background:#f7f9fc;border:1px solid var(--line);border-radius:6px}.trip-request strong{font-size:12px}.trip-request small{display:block;font-size:10px;color:var(--muted);margin-top:4px}.trip-request p{font-size:11px!important;line-height:1.5!important;margin:5px 0 0!important;color:var(--muted)}.terrain-details{margin:12px 0;border-top:1px solid var(--line);padding-top:12px}.terrain-details>summary{cursor:pointer;color:var(--blue);font-size:12px}
.soil-composition{padding:10px;background:#f7f9fc;border-radius:6px;margin:10px 0}.soil-composition h4{font-size:12px;margin:0 0 7px}.soil-composition p{font-size:11px!important;line-height:1.5}.soil-composition small{font-size:10px;color:var(--muted)}
.section-context{margin-top:16px;border-top:1px solid var(--line);padding-top:12px}.position-picker{margin:8px 0;font-size:11px;color:var(--muted)}.position-picker summary{cursor:pointer;color:var(--blue)}.position-picker form{display:grid;gap:6px;margin-top:7px}.position-picker label{display:grid;gap:4px}.position-picker input{width:100%}.position-picker button{justify-self:start;border:1px solid var(--line);border-radius:5px;background:#fff;color:var(--blue);font:inherit;font-size:11px;padding:6px 8px}.position-picker p{font-size:10px;line-height:1.4;margin:5px 0}.section-context h3{font-size:14px;margin:0 0 10px}.section-options{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:5px}.section-option,.context-retry{float:none;border:1px solid var(--line);border-radius:6px;background:#fff;color:var(--ink);font:inherit;font-size:11px;padding:8px 4px;text-align:center}.section-option[aria-pressed=true]{border-color:var(--blue);background:#f4f8ff;color:var(--blue)}.section-option small{display:block;font-size:10px;white-space:nowrap;margin-top:4px}.sample-note,.context-gap{font-size:11px!important;color:var(--muted);line-height:1.5!important}.context-metrics{display:grid;grid-template-columns:1fr 1fr;gap:12px 10px;margin:14px 0}.context-metrics dt{font-size:10px;color:var(--muted)}.context-metrics dd{font-size:13px;font-weight:700;margin:4px 0}.context-metrics small{font-size:9px;color:var(--muted)}.context-sources{font-size:11px;margin-top:12px}.context-sources summary{cursor:pointer;color:var(--blue)}.context-sources small,.context-sources code{display:block;overflow-wrap:anywhere;font-size:10px;margin-top:4px}.context-retry{padding:8px 12px;color:var(--blue);margin-top:8px}
</style>
