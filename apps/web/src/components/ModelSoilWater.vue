<script setup lang="ts">
import { computed } from 'vue'
import type { LngLat } from '../lib/routeTypes'
import type { ModelSoilWaterData, ModelSoilWaterLayer, ModelSoilWaterStatus } from '../lib/modelSoilWaterTypes'

const props = defineProps<{ soilWater?: ModelSoilWaterData | null; selectedPoint?: LngLat; tripDate?: string; sourceDigest?: string | null }>()
const expectedLayers = [
  ['soil_moisture_0_to_1cm', 0, 1],
  ['soil_moisture_1_to_3cm', 1, 3],
  ['soil_moisture_3_to_9cm', 3, 9],
] as const
const statuses: ModelSoilWaterStatus[] = ['available', 'partial', 'unavailable']
function finite(value: unknown): value is number { return typeof value === 'number' && Number.isFinite(value) }
function validPoint(value: unknown): value is LngLat {
  return !!value && typeof value === 'object' && finite((value as LngLat).latitude) && finite((value as LngLat).longitude) && Math.abs((value as LngLat).latitude) <= 90 && Math.abs((value as LngLat).longitude) <= 180
}
function samePoint(a: LngLat, b: LngLat) { return a.latitude === b.latitude && a.longitude === b.longitude }
function validDigest(value: unknown): value is string { return typeof value === 'string' && /^sha256:[0-9a-f]{64}$/.test(value) }
function validDate(value: unknown): value is string {
  if (typeof value !== 'string') return false
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value)
  if (!match) return false
  const [year, month, day] = match.slice(1).map(Number)
  const parsed = new Date(Date.UTC(year, month - 1, day))
  return parsed.getUTCFullYear() === year && parsed.getUTCMonth() === month - 1 && parsed.getUTCDate() === day
}
function validLayer(value: unknown, expected: readonly [string, number, number]): value is ModelSoilWaterLayer {
  if (!value || typeof value !== 'object') return false
  const layer = value as ModelSoilWaterLayer
  if (layer.variable !== expected[0] || layer.from_cm !== expected[1] || layer.to_cm !== expected[2] || !statuses.includes(layer.status) || !Number.isInteger(layer.known_samples) || layer.known_samples < 0 || layer.known_samples > 24 || layer.expected_samples !== 24) return false
  const hasRange = finite(layer.min_m3_m3) && finite(layer.max_m3_m3) && layer.min_m3_m3 >= 0 && layer.max_m3_m3 <= 1 && layer.min_m3_m3 <= layer.max_m3_m3
  if (layer.known_samples === 0) return layer.status === 'unavailable' && layer.min_m3_m3 === null && layer.max_m3_m3 === null
  if (!hasRange) return false
  return layer.status === (layer.known_samples === 24 ? 'available' : 'partial')
}
function aggregateStatus(layers: ModelSoilWaterLayer[]): ModelSoilWaterStatus {
  if (layers.every(layer => layer.status === 'available')) return 'available'
  if (layers.every(layer => layer.status === 'unavailable')) return 'unavailable'
  return 'partial'
}
const display = computed(() => {
  const data = props.soilWater
  if (!data || !validDate(props.tripDate) || !validPoint(props.selectedPoint) || !validDigest(props.sourceDigest) || data.date !== props.tripDate || !validDate(data.date) || data.timezone !== 'UTC' || data.basis !== 'weather_model_not_field_observation' || !statuses.includes(data.status) || data.source_id !== 'open-meteo-icon-global' || data.model !== 'icon_global' || data.source_sha256 !== props.sourceDigest || !validDigest(data.source_sha256) || data.unit !== 'm³/m³' || !validPoint(data.requested_point) || !samePoint(data.requested_point, props.selectedPoint) || !validPoint(data.grid_point) || !Array.isArray(data.layers) || data.layers.length !== expectedLayers.length || !data.layers.every((layer, index) => validLayer(layer, expectedLayers[index])) || data.status !== aggregateStatus(data.layers)) return null
  return data
})
function number(value: number) { return value.toFixed(3).replace('.', ',') }
function coordinate(value: number) { return value.toFixed(6).replace('.', ',') }
</script>

<template>
  <details class="model-soil-water">
    <summary>Модельна вода в ґрунті</summary>
    <template v-if="display">
      <p class="soil-water-intro">Об’ємний вміст води з моделі ICON Global через Open-Meteo.</p>
      <dl class="soil-water-layers">
        <div v-for="layer in display.layers" :key="layer.variable" class="soil-water-layer">
          <dt>{{ layer.from_cm }}–{{ layer.to_cm }} см</dt>
          <dd>{{ layer.min_m3_m3 === null ? '—' : `${number(layer.min_m3_m3)}–${number(layer.max_m3_m3!)} м³/м³` }}</dd>
          <small>{{ layer.known_samples }} / 24 точок<span v-if="layer.status === 'partial'"> · серед відомих точок</span></small>
        </div>
      </dl>
      <p class="soil-water-meta">Запитана точка: {{ coordinate(display.requested_point!.latitude) }}, {{ coordinate(display.requested_point!.longitude) }}. Комірка моделі: {{ coordinate(display.grid_point!.latitude) }}, {{ coordinate(display.grid_point!.longitude) }}.</p>
      <p class="soil-water-note">Це модельний об’ємний вміст води, не виміряна місцева поверхнева вологість; не насичення, не несуча здатність і не дозвіл на рух.</p>
      <p class="soil-water-note">Годинні значення API можуть бути інтерпольовані. 24 / 24 означає повноту ряду API, не незалежні спостереження.</p>
    </template>
    <p v-else class="soil-water-unknown">Модельні дані про воду в ґрунті для обраної точки й дати не узгоджено.</p>
  </details>
</template>

<style scoped>
.model-soil-water{margin:10px 0;font-size:11px}.model-soil-water summary{cursor:pointer;color:var(--blue);font-size:11px}.soil-water-intro,.soil-water-meta,.soil-water-note,.soil-water-unknown{font-size:10px!important;line-height:1.45!important;color:var(--muted);margin:8px 0 0!important}.soil-water-layers{display:grid;gap:8px;margin:9px 0}.soil-water-layer{display:grid;grid-template-columns:minmax(0,1fr)auto;gap:2px 8px}.soil-water-layer dt{font-size:10px;color:var(--muted)}.soil-water-layer dd{font-size:11px;font-weight:700;margin:0}.soil-water-layer small{grid-column:1/-1;font-size:9px;color:var(--muted)}
</style>
