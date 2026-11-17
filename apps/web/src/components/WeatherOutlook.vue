<script setup lang="ts">
import { computed } from 'vue'
import type { WeatherDaySummary, WeatherMetricStatus } from '../lib/weatherDayTypes'
import type { WeatherOutlookData } from '../lib/weatherOutlookTypes'

const props = defineProps<{ outlook: WeatherOutlookData | null | undefined; tripDate: string }>()
const statuses: WeatherMetricStatus[] = ['available', 'partial', 'unavailable']

type DisplayMetric = { value: string | null; known: number | null; incomplete: boolean }
type DisplayDay = { date: string; rain: DisplayMetric; soil: DisplayMetric; snow: DisplayMetric }

function isoDate(value: unknown): value is string {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false
  const date = new Date(`${value}T00:00:00.000Z`)
  return Number.isFinite(date.getTime()) && date.toISOString().slice(0, 10) === value
}
function shiftDate(date: string, days: number): string | null {
  const value = new Date(`${date}T00:00:00.000Z`)
  value.setUTCDate(value.getUTCDate() + days)
  return Number.isFinite(value.getTime()) ? value.toISOString().slice(0, 10) : null
}
function count(value: unknown): value is number { return typeof value === 'number' && Number.isInteger(value) && value >= 0 && value <= 24 }
function finite(value: unknown): value is number { return typeof value === 'number' && Number.isFinite(value) }
function nonNegative(value: unknown): value is number { return finite(value) && value >= 0 }
function range(low: unknown, high: unknown, factor = 1, nonnegative = false): string | null {
  if (!finite(low) || !finite(high) || !finite(low * factor) || !finite(high * factor) || low > high || (nonnegative && low < 0)) return null
  const format = (value: number) => (value * factor).toFixed(1).replace('.', ',')
  return low === high ? format(low) : `${format(low)}–${format(high)}`
}
function unavailable(): DisplayMetric { return { value: null, known: null, incomplete: false } }
function precipitation(metric: unknown): DisplayMetric {
  if (!metric || typeof metric !== 'object') return unavailable()
  const value = metric as WeatherDaySummary['precipitation']
  if (!statuses.includes(value.status) || value.expected_intervals !== 24 || !count(value.known_intervals)) return unavailable()
  if (value.status === 'available' && value.known_intervals === 24 && nonNegative(value.total_mm)) return { value: value.total_mm.toFixed(1).replace('.', ','), known: 24, incomplete: false }
  if (value.status === 'partial' && value.known_intervals > 0 && value.total_mm === null) return { value: null, known: value.known_intervals, incomplete: true }
  if (value.status === 'unavailable' && value.known_intervals === 0 && value.total_mm === null) return { value: null, known: 0, incomplete: false }
  return unavailable()
}
function instantaneous(metric: unknown, kind: 'soil' | 'snow'): DisplayMetric {
  if (!metric || typeof metric !== 'object') return unavailable()
  const value = metric as WeatherDaySummary['soil_temperature'] | WeatherDaySummary['snow_depth']
  const samples = value.known_samples
  const expected = value.expected_samples
  const low = kind === 'soil' ? (value as WeatherDaySummary['soil_temperature']).min_c : (value as WeatherDaySummary['snow_depth']).min_m
  const high = kind === 'soil' ? (value as WeatherDaySummary['soil_temperature']).max_c : (value as WeatherDaySummary['snow_depth']).max_m
  const shown = range(low, high, kind === 'snow' ? 100 : 1, kind === 'snow')
  if (!statuses.includes(value.status) || expected !== 24 || !count(samples)) return unavailable()
  if (value.status === 'available' && samples === 24 && shown) return { value: shown, known: samples, incomplete: false }
  if (value.status === 'partial' && samples > 0 && samples < 24 && shown) return { value: shown, known: samples, incomplete: true }
  if (value.status === 'unavailable' && samples === 0 && low === null && high === null) return { value: null, known: 0, incomplete: false }
  return unavailable()
}
function validDay(day: unknown, expectedDate: string): day is WeatherDaySummary {
  if (!day || typeof day !== 'object') return false
  const value = day as WeatherDaySummary
  return value.date === expectedDate && isoDate(value.date) && value.timezone === 'UTC' && value.basis === 'weather_model_not_field_observation' && statuses.includes(value.status) && 'precipitation' in value && 'soil_temperature' in value && 'snow_depth' in value
}
function validOutlook(value: unknown, tripDate: string): value is WeatherOutlookData {
  if (!isoDate(tripDate) || !value || typeof value !== 'object') return false
  const outlook = value as WeatherOutlookData
  if (outlook.date !== tripDate || !isoDate(outlook.date) || outlook.timezone !== 'UTC' || outlook.basis !== 'weather_model_not_field_observation' || outlook.horizon_days !== 2 || !statuses.includes(outlook.status) || !Array.isArray(outlook.days) || outlook.days.length > 2) return false
  if (!outlook.days.every((day, index) => {
    const expected = shiftDate(tripDate, index + 1)
    return expected !== null && validDay(day, expected)
  })) return false
  const complete = outlook.days.length === 2 && outlook.days.every(day => day.status === 'available')
  const anyKnown = outlook.days.some(day => day.status !== 'unavailable')
  return outlook.status === (complete ? 'available' : anyKnown ? 'partial' : 'unavailable')
}
function displayDay(day: WeatherDaySummary): DisplayDay {
  return { date: day.date, rain: precipitation(day.precipitation), soil: instantaneous(day.soil_temperature, 'soil'), snow: instantaneous(day.snow_depth, 'snow') }
}
const days = computed(() => validOutlook(props.outlook, props.tripDate) && props.outlook.days.length > 0 ? props.outlook.days.map(displayDay) : null)
</script>

<template>
  <section class="weather-outlook-container" aria-label="Погода наступних двох днів">
    <template v-if="days">
      <details class="weather-outlook">
        <summary>Наступні 2 дні · погода</summary>
        <div v-for="day in days" :key="day.date" class="outlook-day" :data-date="day.date">
          <h4>{{ day.date }} · UTC</h4>
          <dl>
            <div class="outlook-rain"><dt>Опади за добу</dt><dd>{{ day.rain.value === null ? '—' : day.rain.value }} мм</dd><small v-if="day.rain.known !== null">{{ day.rain.known }} / 24 інтервалів<span v-if="day.rain.value === null && day.rain.known > 0"> · Повну добову суму не отримано</span></small></div>
            <div class="outlook-soil"><dt>Модельна температура поверхні</dt><dd>{{ day.soil.value === null ? '—' : day.soil.value }} °C</dd><small v-if="day.soil.known !== null">{{ day.soil.known }} / 24 точок<span v-if="day.soil.incomplete"> · Неповна вибірка</span></small></div>
            <div class="outlook-snow"><dt>Модельний сніговий покрив</dt><dd>{{ day.snow.value === null ? '—' : day.snow.value }} см</dd><small v-if="day.snow.known !== null">{{ day.snow.known }} / 24 точок<span v-if="day.snow.incomplete"> · Неповна вибірка</span></small></div>
          </dl>
        </div>
        <p>Прогноз моделі не є оцінкою висихання чи проїзності. Горизонт моделі може бути коротшим; пропущені дані не означають сухий ґрунт.</p>
      </details>
    </template>
    <p v-else class="weather-outlook-unknown">Немає узгоджених даних для обраної дати.</p>
  </section>
</template>

<style scoped>
.weather-outlook{border-top:1px solid var(--line);margin-top:10px;padding-top:10px}.weather-outlook details{margin:0}.weather-outlook summary{cursor:pointer;font-size:10px;color:var(--muted)}.outlook-day{padding:10px 0;border-bottom:1px solid var(--line)}.outlook-day h4{font-size:11px;margin:0 0 7px}.outlook-day dl{display:grid;gap:8px;margin:0}.outlook-day dl>div{display:grid;grid-template-columns:minmax(0,1fr)auto;gap:2px 8px}.outlook-day dt,.outlook-day small,.weather-outlook p{font-size:10px;color:var(--muted)}.outlook-day dd{font-size:12px;font-weight:700;margin:0}.outlook-day small{grid-column:1/-1}.weather-outlook p{line-height:1.45;margin:9px 0 0}.weather-outlook-unknown{margin:0!important}
</style>
