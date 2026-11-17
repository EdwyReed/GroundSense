<script setup lang="ts">
import { computed } from 'vue'
import type { LngLat } from '../lib/routeTypes'
import type { SurfaceObservationData } from '../lib/sectionContextTypes'

const props = defineProps<{ observation?: SurfaceObservationData | null; selectedPoint: LngLat; tripDate: string }>()

type Display = { code: number; label: string; className: string; observedDate: string; age: number; resolution: number }
const classes: Record<number, { condition: string; label: string; className: string; status: 'available' | 'partial' }> = {
  4: { condition: 'vegetation', label: 'Рослинність', className: 'is-vegetation', status: 'available' },
  5: { condition: 'not_vegetated', label: 'Без рослинності', className: 'is-not-vegetated', status: 'available' },
  6: { condition: 'water', label: 'вода', className: 'is-water', status: 'available' },
  2: { condition: 'shadow', label: 'Тінь', className: 'is-shadow', status: 'partial' },
  3: { condition: 'shadow', label: 'Тінь від хмар', className: 'is-shadow', status: 'partial' },
  8: { condition: 'cloud', label: 'Хмари', className: 'is-cloud', status: 'partial' },
  9: { condition: 'cloud', label: 'Хмари', className: 'is-cloud', status: 'partial' },
  10: { condition: 'cloud', label: 'Тонкі перисті хмари', className: 'is-cloud', status: 'partial' },
  11: { condition: 'snow_ice', label: 'Сніг / лід', className: 'is-snow-ice', status: 'partial' },
}
function utcInstant(value: unknown) {
  if (typeof value !== 'string') return null
  const match = value.match(/^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d{1,6}))?Z$/)
  if (!match) return null
  const date = new Date(value)
  const fraction = (match[2] || '').padEnd(6, '0')
  if (!Number.isFinite(date.getTime()) || date.toISOString() !== `${match[1]}.${fraction.slice(0, 3)}Z`) return null
  return { date, key: `${match[1]}.${fraction}Z` }
}
function utcDate(value: unknown) { return typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value) && !Number.isNaN(Date.parse(`${value}T00:00:00Z`)) && new Date(`${value}T00:00:00Z`).toISOString().slice(0, 10) === value ? value : null }
const display = computed<Display | null>(() => {
  const item = props.observation
  if (!item || typeof item.scl_class !== 'number' || !Number.isInteger(item.scl_class) || typeof item.resolution_m !== 'number' || !Number.isFinite(item.resolution_m) || item.resolution_m <= 0) return null
  const code = item.scl_class, resolution = item.resolution_m, expected = classes[code]
  const selectedDate = utcDate(props.tripDate), observed = utcInstant(item.observed_at), retrieved = utcInstant(item.retrieved_at)
  if (!expected || !selectedDate || !observed || !retrieved || item.status !== expected.status || item.basis !== 'sentinel2_l2a_scl_point' || item.assessment_date !== selectedDate || item.condition !== expected.condition || item.requested_point?.latitude !== props.selectedPoint.latitude || item.requested_point?.longitude !== props.selectedPoint.longitude || observed.key > retrieved.key) return null
  const observedDate = observed.date.toISOString().slice(0, 10), age = (Date.parse(`${selectedDate}T00:00:00Z`) - Date.parse(`${observedDate}T00:00:00Z`)) / 86400000
  if (!Number.isInteger(age) || age < 0 || item.scene_age_days !== age) return null
  return { code, label: expected.label, className: expected.className, observedDate, age, resolution }
})
function days(value: number) { const form = new Intl.PluralRules('uk').select(value); return `${value} ${form === 'one' ? 'доба' : form === 'few' ? 'доби' : 'діб'} до дати поїздки` }
</script>

<template>
  <section class="surface-observation" :class="display?.className || 'is-unknown'" aria-label="Супутникове спостереження">
    <header><h4>Супутникове спостереження</h4><span v-if="display">{{ display.observedDate }} · UTC</span></header>
    <template v-if="display">
      <p class="surface-class">Клас SCL {{ display.code }} · {{ display.label }}</p>
      <p class="surface-meta">{{ days(display.age) }} · Рідна комірка {{ display.resolution }} м</p>
      <p class="surface-meta">Sentinel-2 L2A · AWS Earth Search</p>
    </template>
    <p v-else class="surface-unknown">Немає узгодженого супутникового спостереження для обраної ділянки.</p>
    <p class="surface-note">Точкова класифікація сцени, не оцінка проїзності чи стану поверхні на дату поїздки.</p>
  </section>
</template>

<style scoped>
.surface-observation{border:1px solid var(--line);border-radius:6px;padding:11px;margin:14px 0;background:#f8faff;border-left-width:4px}.surface-observation header{display:flex;justify-content:space-between;gap:8px;align-items:center}.surface-observation h4{font-size:12px;margin:0}.surface-observation header span,.surface-meta,.surface-note,.surface-unknown{font-size:10px!important;line-height:1.45!important;color:var(--muted);margin:7px 0 0!important}.surface-observation header span{margin:0!important;white-space:nowrap}.surface-class{font-size:12px;font-weight:700;margin:9px 0 0}.is-water{border-left-color:#3178b8}.is-vegetation{border-left-color:#5f8e55}.is-not-vegetated{border-left-color:#9a8254}.is-shadow{border-left-color:#6f7680}.is-cloud{border-left-color:#8493a2}.is-snow-ice{border-left-color:#89aecd}.is-unknown{border-left-color:#9aa3ad}
</style>
