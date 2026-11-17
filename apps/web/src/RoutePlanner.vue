<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { ApiClient } from './lib/api'
import RouteMap from './components/RouteMap.vue'
import SectionContext from './components/SectionContext.vue'
import TerrainProfile from './components/TerrainProfile.vue'
import type { RouteSection } from './lib/sectionContextTypes'
import type { LandCoverTrace } from './lib/landCoverTraceTypes'
import type { LngLat, PlaceSearch, RouteAlternative, RouteApiClient, RoutePlan, VehicleKind } from './lib/routeTypes'
import { isTerrainAnalysis, isTerrainGeometry } from './lib/routeTypes'
import { sectionForChainage } from './lib/transectSelection'
import './route-planner.css'

const props = defineProps<{ client?: RouteApiClient; csrfToken?: string; initialMode?: 'terrain' | 'road' }>()
const mode = ref<'terrain' | 'road'>(props.initialMode || 'terrain')
const sessionClient = ref<RouteApiClient | null>(null)
const client = computed<RouteApiClient | null>(() => props.client || (props.csrfToken ? new ApiClient(props.csrfToken) : sessionClient.value))
const origin = ref<LngLat | null>(null), destination = ref<LngLat | null>(null)
const selecting = ref<'origin' | 'destination' | null>(null)
const query = ref(''), places = ref<LngLat[]>([]), searchBusy = ref(false), routeBusy = ref(false)
const tripDate = ref(''), vehicle = ref<VehicleKind>('truck_6x6'), mass = ref<number>(20)
const plan = ref<RoutePlan | null>(null), selectedRouteId = ref<string | null>(null), error = ref(''), mapStatus = ref('')
const detailOpen = ref(false), editingTrip = ref(true)
const inspectorHeading = ref<HTMLElement>()
const inspectedSection = ref<RouteSection | null>(null)
const routeSections = ref<RouteSection[]>([]), selectedSectionIndex = ref(0), previewSectionIndex = ref<number | null>(null)
const selectedChainage = ref<number | null>(null), inspectionPoint = ref<LngLat | null>(null)
const landCoverTrace = ref<LandCoverTrace | null>(null)
let routeRevision = 0, searchRevision = 0
const selectedRoute = computed<RouteAlternative | null>(() => plan.value?.routes.find(route => route.id === selectedRouteId.value) || null)
const canPlan = computed(() => !!client.value && !!origin.value && !!destination.value && !!tripDate.value && Number.isFinite(mass.value) && mass.value > 0 && !routeBusy.value)
const searchReason = computed(() => selecting.value ? 'Введіть назву місця та натисніть пошук' : 'Оберіть, для якої точки шукати місце')
const vehicleOptions: { value: VehicleKind; label: string }[] = [{ value: 'car', label: 'Легковий автомобіль' }, { value: 'truck_4x4', label: 'Вантажівка 4×4' }, { value: 'truck_6x6', label: 'Вантажівка 6×6' }]
function formatDistance(distance: number) { return distance >= 1000 ? `${(distance / 1000).toFixed(1).replace('.', ',')} км` : `${Math.round(distance)} м` }
function localDate() { const date = new Date(); return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}` }
function coordinatePair(value: string): LngLat | 'invalid' | null {
  const match = value.match(/^\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s*,\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s*$/)
  if (!match) return null
  const latitude = Number(match[1]), longitude = Number(match[2])
  if (!Number.isFinite(latitude) || !Number.isFinite(longitude) || latitude < -90 || latitude > 90 || longitude < -180 || longitude > 180) return 'invalid'
  return { latitude, longitude, label: `${latitude.toFixed(5)}, ${longitude.toFixed(5)}` }
}
function invalidate() { routeRevision++; routeBusy.value = false; plan.value = null; selectedRouteId.value = null; landCoverTrace.value = null; detailOpen.value = false; editingTrip.value = true; error.value = ''; routeSections.value = []; selectedSectionIndex.value = 0; selectedChainage.value = null; inspectionPoint.value = null; previewSectionIndex.value = null; inspectedSection.value = null }
function openDetails(id: string) { selectedRouteId.value = id; detailOpen.value = true }
function toggleTripEditor() { editingTrip.value = !editingTrip.value; if (editingTrip.value) detailOpen.value = false }
function chooseSection(index: number) { if (!selectedRoute.value || !Number.isInteger(index) || !routeSections.value.some(section => section.index === index)) return; previewSectionIndex.value = null; selectedChainage.value = null; inspectionPoint.value = null; selectedSectionIndex.value = index; detailOpen.value = true }
function chooseChainage(chainage: number | null) {
  if (chainage === null) { selectedChainage.value = null; inspectionPoint.value = null; return }
  const section = sectionForChainage(routeSections.value, chainage, selectedSectionIndex.value)
  if (!selectedRoute.value || !isTerrainGeometry(selectedRoute.value.geometry_kind) || !section || !Number.isFinite(chainage)) return
  previewSectionIndex.value = null; inspectionPoint.value = null; selectedSectionIndex.value = section.index; selectedChainage.value = chainage; detailOpen.value = true
}
function chooseProfilePoint(chainage: number) {
  chooseChainage(chainage)
  if (selectedChainage.value === chainage) nextTick(() => inspectorHeading.value?.focus({ preventScroll: true }))
}
function assignPoint(kind: 'origin' | 'destination', point: LngLat) { if (kind === 'origin') origin.value = point; else destination.value = point; selecting.value = null }
function pointFromMap(point: LngLat) { if (selecting.value) assignPoint(selecting.value, point) }
function swap() { const a = origin.value; origin.value = destination.value; destination.value = a; invalidate() }
function loadExample() {
  origin.value = mode.value === 'terrain' ? { longitude: 32.536, latitude: 50.253, label: 'Удай A' } : { longitude: 10.7387, latitude: 59.9139, label: 'Осло A' }
  destination.value = mode.value === 'terrain' ? { longitude: 32.56, latitude: 50.267, label: 'Удай B' } : { longitude: 10.7849, latitude: 59.9399, label: 'Осло B' }
  tripDate.value = localDate(); invalidate()
}
async function searchPlaces() {
  const target = selecting.value, value = query.value.trim(), revision = ++searchRevision
  if (!target || !value || !client.value) return
  const coordinates = coordinatePair(value)
  if (coordinates === 'invalid') { error.value = 'Широта має бути від -90 до 90, довгота — від -180 до 180.'; return }
  if (coordinates) { error.value = ''; assignPoint(target, coordinates); places.value = []; query.value = ''; return }
  searchBusy.value = true; error.value = ''; places.value = []
  try {
    const result = await client.value.get<PlaceSearch>(`/places?q=${encodeURIComponent(value)}`)
    if (revision !== searchRevision || target !== selecting.value) return
    places.value = result.places || []
    if (result.status !== 'ready') error.value = 'Пошук місць недоступний. Виберіть точку на карті.'
    else if (!places.value.length) error.value = 'Місце не знайдено. Уточніть назву або виберіть точку на карті.'
  }
  catch (cause: any) { if (revision === searchRevision) error.value = cause?.message || 'Не вдалося знайти місце' }
  finally { if (revision === searchRevision) searchBusy.value = false }
}
function choosePlace(place: LngLat) { if (!selecting.value) return; assignPoint(selecting.value, place); places.value = []; query.value = '' }
async function requestRoutes() {
  if (!canPlan.value || !origin.value || !destination.value || !client.value) return
  const revision = ++routeRevision; routeBusy.value = true; error.value = ''; plan.value = null; selectedRouteId.value = null; landCoverTrace.value = null
  const body = { origin: origin.value, destination: destination.value, trip_date: tripDate.value, vehicle: { kind: vehicle.value, gross_mass_t: Number(mass.value) } }
  try {
    const result = await client.value.post<RoutePlan>(mode.value === 'terrain' ? '/terrain-path-plans' : '/route-plans', body)
    if (revision !== routeRevision) return
    plan.value = result; selectedRouteId.value = result.routes[0]?.id || null; editingTrip.value = !result.routes.length
    detailOpen.value = mode.value === 'terrain' && !!result.routes.length
  } catch (cause: any) { if (revision === routeRevision) error.value = cause?.message || 'Не вдалося побудувати маршрут' }
  finally { if (revision === routeRevision) routeBusy.value = false }
}
watch([origin, destination, tripDate, vehicle, mass, mode], invalidate)
watch([query, selecting], () => { searchRevision++; searchBusy.value = false; places.value = [] }, { flush: 'sync' })
watch(selectedRouteId, () => { landCoverTrace.value = null; inspectedSection.value = null; inspectionPoint.value = null; selectedChainage.value = null; routeSections.value = []; selectedSectionIndex.value = 0; previewSectionIndex.value = null })
watch(detailOpen, () => { inspectedSection.value = null; inspectionPoint.value = null; previewSectionIndex.value = null })
onMounted(async () => {
  if (props.client || props.csrfToken) return
  try {
    const response = await fetch('/api/v1/bootstrap', { credentials: 'same-origin' })
    if (!response.ok) throw new Error()
    const bootstrap = await response.json()
    if (typeof bootstrap.csrf_token !== 'string' || !bootstrap.csrf_token) throw new Error()
    sessionClient.value = new ApiClient(bootstrap.csrf_token)
  } catch { error.value = 'Не вдалося відкрити сесію. Оновіть сторінку, щоб повторити.' }
})
</script>

<template>
  <main class="route-planner">
    <header class="route-header"><a class="brand" href="#" aria-label="GroundSense"><span>⌁</span> GroundSense</a><span class="route-mode">{{ mode === 'terrain' ? 'Пошук бездоріжжям' : 'Планування маршруту' }}</span><button class="reference-button" type="button" @click="loadExample">{{ mode === 'terrain' ? 'Контрольний приклад · долина Удаю' : 'Контрольний приклад · Норвегія' }}</button></header>
    <aside class="route-sidebar" :class="{ 'editing-trip': editingTrip, 'has-results': !!plan?.routes.length, inspecting: detailOpen }">
      <button v-if="plan?.routes.length" type="button" class="edit-trip" @click="toggleTripEditor">{{ origin?.label || 'A' }} → {{ destination?.label || 'B' }} <span>{{ editingTrip ? 'До варіантів' : 'Змінити поїздку' }}</span></button>
      <section class="trip-form" aria-labelledby="planner-title"><div class="analysis-modes" aria-label="Спосіб аналізу"><button type="button" data-mode="terrain" :aria-pressed="mode === 'terrain'" @click="mode = 'terrain'">Місцевість без доріг</button><button type="button" data-mode="road" :aria-pressed="mode === 'road'" @click="mode = 'road'">Дорожні маршрути</button></div><h1 id="planner-title">{{ mode === 'terrain' ? 'Пошук бездоріжжям' : 'Планування маршруту' }}</h1>
        <p v-if="mode === 'terrain'" class="terrain-intro">Попередні шляхи за покривом 2021 і DSM. До 20 км. Дата й маса поки не змінюють пошук; проїзд не підтверджено.</p>
        <div class="point-grid"><label>Звідки<button type="button" class="point-button" data-testid="pick-origin" :class="{ active: selecting === 'origin' }" @click="selecting = 'origin'">⌖ {{ origin?.label || 'Точка A' }}</button></label><button class="swap" type="button" aria-label="Поміняти точки місцями" @click="swap">⇄</button><label>Куди<button type="button" class="point-button" :class="{ active: selecting === 'destination' }" @click="selecting = 'destination'">⌖ {{ destination?.label || 'Точка B' }}</button></label></div>
        <p v-if="selecting" class="pick-hint">Виберіть точку {{ selecting === 'origin' ? 'A' : 'B' }} на карті або знайдіть місце.</p>
        <form class="place-search" @submit.prevent="searchPlaces"><input v-model="query" :disabled="!selecting" aria-label="Пошук місця" placeholder="Пошук місця"><button type="submit" :disabled="!selecting || !query.trim() || searchBusy" :title="searchReason">{{ searchBusy ? '…' : 'Пошук' }}</button></form><p class="coordinate-hint">Або введіть координати: широта, довгота (наприклад, 59.9139, 10.7387).</p>
        <ul v-if="places.length" class="place-results"><li v-for="place in places" :key="`${place.longitude}-${place.latitude}`"><button type="button" @click="choosePlace(place)">{{ place.label || `${place.latitude.toFixed(5)}, ${place.longitude.toFixed(5)}` }}</button></li></ul>
        <div class="fields"><label>Дата поїздки<input v-model="tripDate" type="date"></label><label>Транспортний засіб<select v-model="vehicle"><option v-for="option in vehicleOptions" :key="option.value" :value="option.value">{{ option.label }}</option></select></label><label class="mass-field">Повна маса<input v-model.number="mass" type="number" min="0.1" step="0.1" inputmode="decimal"><span>т</span></label></div>
        <button class="plan-button" type="button" :disabled="!canPlan" @click="requestRoutes">{{ routeBusy ? 'Завантажуємо…' : mode === 'terrain' ? 'Знайти шляхи' : 'Оновити маршрути' }}</button>
        <p v-if="!origin || !destination" class="empty-state">Оберіть точки A і B на карті або через пошук.</p><p v-if="error" class="form-error" role="alert">{{ error }}</p><p v-if="mapStatus" class="form-error">{{ mapStatus }}</p>
      </section>
      <section class="route-results" aria-live="polite"><div class="results-title"><h2>{{ mode === 'terrain' ? 'Кандидати шляху' : 'Варіанти маршруту' }}</h2><span v-if="plan && mode === 'road'">{{ plan.routes.length }} {{ plan.routes.length === 1 ? 'варіант' : 'варіанти' }}</span></div>
        <p v-if="plan && !plan.routes.length" class="empty-state">{{ plan.warnings_uk[0] || 'Маршрутів не знайдено.' }}</p>
        <button v-for="route in plan?.routes || []" :key="route.id" type="button" class="route-card" :class="{ selected: selectedRouteId === route.id }" @click="selectedRouteId = route.id"><span class="route-radio" aria-hidden="true"></span><span class="route-copy"><strong>{{ route.name }}</strong><small>{{ route.conditions.summary_uk }}</small></span><b>{{ formatDistance(route.distance_m) }}</b></button>
        <p v-if="plan?.warnings_uk?.length" class="disclosure">{{ plan.warnings_uk[0] }}</p>
        <p v-if="plan?.routes.length" class="disclosure">Прогноз на дату — у деталях ділянки. Проїзд для обраного транспорту й маси ще не оцінено.</p>
        <button v-if="selectedRoute" data-testid="route-details" class="details-button" type="button" @click="openDetails(selectedRoute.id)">{{ mode === 'terrain' ? 'Дані ділянок ↗' : 'Деталі маршруту ↗' }}</button>
      </section>
      <TerrainProfile v-if="client && selectedRoute && plan?.plan_id && isTerrainAnalysis(plan.analysis_kind)" :key="`profile:${plan.plan_id}:${selectedRoute.id}`" :client="client" :plan-id="plan.plan_id" :route-id="selectedRoute.id" :trip-date="plan.request.trip_date" :route-geometry="selectedRoute.geometry" :inspection-ready="routeSections.length > 0" @refresh="requestRoutes" @trace="landCoverTrace = $event" @inspect-point="chooseProfilePoint" />
      <article v-if="selectedRoute && detailOpen" class="route-drawer">
        <button aria-label="Закрити деталі" type="button" @click="detailOpen = false">×</button><h2 ref="inspectorHeading" tabindex="-1">{{ isTerrainAnalysis(plan?.analysis_kind) ? 'Умови для поїздки' : selectedRoute.name }}</h2><strong>{{ formatDistance(selectedRoute.distance_m) }}</strong>
        <p v-if="plan?.analysis_kind === 'terrain_candidate'">Кандидат · проїзд не підтверджено.</p>
        <p v-else-if="plan?.analysis_kind === 'terrain_transect'">Лінія аналізу, не шлях проїзду.</p>
        <template v-else><p>{{ selectedRoute.conditions.summary_uk }}</p><p>Проїзність для обраного транспорту не оцінено.</p><p>Джерело: OSRM · автомобільний профіль.<br>Отримано: {{ plan?.source?.retrieved_at }}</p></template>
        <SectionContext v-if="client && plan?.plan_id" :key="`${plan.plan_id}:${selectedRoute.id}`" :client="client" :plan-id="plan.plan_id" :route-id="selectedRoute.id" :trip-date="plan.request.trip_date" :route-geometry="selectedRoute.geometry" :analysis-kind="plan.analysis_kind" :vehicle="plan.request.vehicle" :selected-section-index="selectedSectionIndex" :selected-chainage="selectedChainage" @section="inspectedSection = $event" @sample-point="inspectionPoint = $event" @sections="routeSections = $event" @select-section="chooseSection" @select-chainage="chooseChainage" @preview-section="previewSectionIndex = $event" @refresh="requestRoutes" />
        <details v-if="plan?.analysis_kind === 'terrain_candidate'"><summary>Як знайдено кандидата</summary><p>A* по області навколо A/B. Відносні переваги покриву й перепади DSM — не фізична модель машини. Альтернатива за відстанню має ті самі виключені комірки.</p><p>Забудову, сніг/лід і постійні водойми WorldCover 2021 виключено за політикою; невідомі комірки не вважаються відкритими. Це не поточні спостереження. Просвіти в лісі, несуча здатність, дата й маса не визначають пошук.</p></details>
      </article>
    </aside>
    <section class="map-area"><RouteMap :origin="origin" :destination="destination" :routes="plan?.routes || []" :selected-route-id="selectedRouteId" :selecting="selecting" :land-cover-trace="landCoverTrace" :sections="routeSections" :selected-section-index="selectedSectionIndex" :preview-section-index="previewSectionIndex" :inspected-section="inspectedSection" :inspection-point="inspectionPoint" :inspecting="detailOpen" @point="pointFromMap" @select-point="selecting = $event" @route="openDetails" @section="chooseSection" @line-chainage="chooseChainage" @preview-section="previewSectionIndex = $event" @status="mapStatus = $event" /></section>
  </main>
</template>
