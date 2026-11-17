<script setup lang="ts">
import { computed } from 'vue'
import type { AntecedentPrecipitationDay, AntecedentPrecipitationSummary, AntecedentPrecipitationStatus } from '../lib/antecedentPrecipitationTypes'

const props = defineProps<{ summary: AntecedentPrecipitationSummary; tripDate: string }>()
const statuses: AntecedentPrecipitationStatus[] = ['available', 'partial', 'unavailable']

function isoDate(value: unknown): value is string {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false
  const date = new Date(`${value}T00:00:00.000Z`)
  return Number.isFinite(date.getTime()) && date.toISOString().slice(0, 10) === value
}
function shiftDate(date: string, days: number) {
  const value = new Date(`${date}T00:00:00.000Z`); value.setUTCDate(value.getUTCDate() + days)
  return value.toISOString().slice(0, 10)
}
function whole(value: unknown, maximum: number) { return typeof value === 'number' && Number.isInteger(value) && value >= 0 && value <= maximum }
function millimetres(value: unknown): value is number { return typeof value === 'number' && Number.isFinite(value) && value >= 0 }
function validDay(day: unknown, date: string): day is AntecedentPrecipitationDay {
  if (!day || typeof day !== 'object') return false
  const candidate = day as AntecedentPrecipitationDay
  if (candidate.date !== date || !statuses.includes(candidate.status) || candidate.expected_intervals !== 24 || !whole(candidate.known_intervals, 24)) return false
  const complete = candidate.known_intervals === 24 && candidate.status === 'available' && millimetres(candidate.total_mm)
  const partial = candidate.known_intervals > 0 && candidate.known_intervals <= 24 && candidate.status === 'partial' && candidate.total_mm === null
  const unavailable = candidate.known_intervals === 0 && candidate.status === 'unavailable' && candidate.total_mm === null
  return complete || partial || unavailable
}
function validSummary(value: unknown, tripDate: string): value is AntecedentPrecipitationSummary {
  if (!isoDate(tripDate) || !value || typeof value !== 'object') return false
  const summary = value as AntecedentPrecipitationSummary
  if (summary.date !== tripDate || summary.timezone !== 'UTC' || summary.basis !== 'weather_model_not_field_observation' || summary.window_start !== shiftDate(tripDate, -7) || summary.window_end_exclusive !== tripDate || summary.window_days !== 7 || summary.expected_intervals !== 168 || !statuses.includes(summary.status) || !whole(summary.known_intervals, 168) || !Array.isArray(summary.days) || summary.days.length !== 7) return false
  if (!summary.days.every((day, index) => validDay(day, shiftDate(tripDate, index - 7)))) return false
  const known = summary.days.reduce((sum, day) => sum + day.known_intervals, 0)
  if (known !== summary.known_intervals) return false
  const complete = known === 168 && summary.days.every(day => day.status === 'available') && summary.status === 'available' && millimetres(summary.total_mm) && Math.abs(summary.total_mm - summary.days.reduce((sum, day) => sum + (day.total_mm as number), 0)) < 1e-9
  const partial = known > 0 && known <= 168 && summary.status === 'partial' && summary.total_mm === null
  const unavailable = known === 0 && summary.status === 'unavailable' && summary.total_mm === null
  return complete || partial || unavailable
}
function number(value: number | null) { return millimetres(value) ? value.toFixed(1).replace('.', ',') : '—' }

const summary = computed(() => validSummary(props.summary, props.tripDate) ? props.summary : null)
const dates = computed(() => isoDate(props.tripDate) ? `${shiftDate(props.tripDate, -7)} — ${shiftDate(props.tripDate, -1)} · UTC` : '— · UTC')
</script>

<template>
  <section class="antecedent-precipitation" aria-label="Опади до поїздки">
    <template v-if="summary">
      <header><h4>Опади до поїздки</h4><span>{{ dates }}</span></header>
      <div class="antecedent-metric"><span>За 7 попередніх діб</span><strong class="antecedent-total">{{ number(summary.total_mm) }} мм</strong></div>
      <small>{{ summary.known_intervals }} / 168 інтервалів<span v-if="summary.total_mm === null"> · Повну суму не отримано</span></small>
      <details><summary>Добові суми</summary><ul><li v-for="day in summary.days" :key="day.date">{{ day.date }}: {{ number(day.total_mm) }} мм · {{ day.known_intervals }} / 24</li></ul></details>
      <p>Модельні дані: архів прогнозів і прогноз залежно від дати. Опади не є виміряною вологістю ґрунту чи проїзністю.</p>
    </template>
    <p v-else>Немає узгоджених даних для обраної дати.</p>
  </section>
</template>

<style scoped>
.antecedent-precipitation{border-top:1px solid var(--line);margin-top:10px;padding-top:10px}.antecedent-precipitation header{display:flex;justify-content:space-between;align-items:center;gap:8px}.antecedent-precipitation h4{font-size:12px;margin:0}.antecedent-precipitation header span,.antecedent-precipitation small,.antecedent-precipitation p,.antecedent-precipitation li,.antecedent-precipitation summary{font-size:10px;color:var(--muted)}.antecedent-precipitation header span{font-size:9px;white-space:nowrap}.antecedent-metric{display:flex;justify-content:space-between;gap:8px;margin-top:7px;font-size:10px;color:var(--muted)}.antecedent-metric strong{font-size:12px;color:inherit}.antecedent-precipitation details{margin-top:8px}.antecedent-precipitation summary{cursor:pointer}.antecedent-precipitation ul{margin:5px 0 0;padding-left:16px}.antecedent-precipitation p{line-height:1.45;margin:8px 0 0}
</style>
