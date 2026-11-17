<script setup lang="ts">
import { computed } from 'vue'
import type { WeatherDaySummary } from '../lib/weatherDayTypes'
import type { AntecedentPrecipitationSummary } from '../lib/antecedentPrecipitationTypes'
import AntecedentPrecipitation from './AntecedentPrecipitation.vue'
import WeatherOutlook from './WeatherOutlook.vue'
import type { WeatherOutlookData } from '../lib/weatherOutlookTypes'
import ModelSoilWater from './ModelSoilWater.vue'
import type { LngLat } from '../lib/routeTypes'
import type { ModelSoilWaterData } from '../lib/modelSoilWaterTypes'
const props = defineProps<{ summary: WeatherDaySummary; tripDate: string; antecedent?: AntecedentPrecipitationSummary; outlook?: WeatherOutlookData | null; soilWater?: ModelSoilWaterData | null; showSoilWater?: boolean; selectedPoint?: LngLat; sourceDigest?: string | null }>()
const bound = computed(() => props.summary?.date === props.tripDate && props.summary.timezone === 'UTC' && props.summary.basis === 'weather_model_not_field_observation')
const rain = computed(() => {
  const metric = props.summary.precipitation
  return metric.status === 'available' && metric.known_intervals === 24 && metric.expected_intervals === 24 && typeof metric.total_mm === 'number' && metric.total_mm >= 0 ? metric.total_mm : null
})
function number(value: number | null) { return typeof value === 'number' && Number.isFinite(value) ? value.toFixed(1).replace('.', ',') : '—' }
function range(low: number | null, high: number | null, factor = 1, nonNegative = false) {
  if (typeof low !== 'number' || typeof high !== 'number' || !Number.isFinite(low * factor) || !Number.isFinite(high * factor) || low > high || nonNegative && low < 0) return '—'
  return low === high ? number(low * factor) : `${number(low * factor)}–${number(high * factor)}`
}
</script>

<template>
  <section class="weather-day" aria-label="Модельні погодні умови на дату">
    <header><h4>Погода на дату</h4><span>{{ tripDate }} · UTC</span></header>
    <template v-if="bound"><dl class="weather-day-metrics">
      <div class="day-precipitation"><dt>Опади за добу</dt><dd>{{ number(rain) }} мм</dd><small>{{ props.summary.precipitation.known_intervals }} / 24 інтервалів<span v-if="rain === null"> · Повну добову суму не отримано</span></small></div>
      <div class="day-soil-temperature"><dt>Поверхня ґрунту · 0 см</dt><dd>{{ range(props.summary.soil_temperature.min_c, props.summary.soil_temperature.max_c) }} °C</dd><small>{{ props.summary.soil_temperature.known_samples }} / 24 точок<span v-if="props.summary.soil_temperature.known_samples < 24"> · Неповна вибірка</span></small></div>
      <div class="day-snow"><dt>Модельний сніговий покрив</dt><dd>{{ range(props.summary.snow_depth.min_m, props.summary.snow_depth.max_m, 100, true) }} см</dd><small>{{ props.summary.snow_depth.known_samples }} / 24 точок<span v-if="props.summary.snow_depth.known_samples < 24"> · Неповна вибірка</span></small></div>
    </dl>
    <p v-if="props.summary.soil_temperature.known_samples > 0" class="weather-zero-count">{{ props.summary.soil_temperature.at_or_below_zero_samples }} / {{ props.summary.soil_temperature.known_samples }} точок ≤ 0 °C</p>
    <p class="weather-day-note">Модельна комірка, не місцеве вимірювання. Сніг і температура поверхні не підтверджують промерзання в глибину, затоплення чи можливість проїзду.</p>
    <AntecedentPrecipitation v-if="props.antecedent" :summary="props.antecedent" :trip-date="props.tripDate" />
    <WeatherOutlook v-if="props.outlook" :outlook="props.outlook" :trip-date="props.tripDate" />
    <ModelSoilWater v-if="props.showSoilWater || props.soilWater !== undefined" :soil-water="props.soilWater" :selected-point="props.selectedPoint" :trip-date="props.tripDate" :source-digest="props.sourceDigest" />
    </template><p v-else class="weather-day-note">Немає узгоджених даних для обраної дати.</p>
  </section>
</template>

<style scoped>
.weather-day{border:1px solid var(--line);border-radius:6px;padding:11px;margin:14px 0;background:#f8faff}.weather-day header{display:flex;justify-content:space-between;gap:8px;align-items:center}.weather-day h4{font-size:12px;margin:0}.weather-day header span{font-size:9px;color:var(--muted);white-space:nowrap}.weather-day-metrics{margin:10px 0 0;display:grid;gap:9px}.weather-day-metrics>div{display:grid;grid-template-columns:minmax(0,1fr)auto;gap:3px 8px}.weather-day-metrics dt{font-size:10px;color:var(--muted)}.weather-day-metrics dd{font-size:12px;font-weight:700;margin:0}.weather-day-metrics small{font-size:9px;color:var(--muted);grid-column:1/-1}.weather-day-note,.weather-zero-count{font-size:10px!important;line-height:1.45!important;color:var(--muted);margin:9px 0 0!important}
</style>
