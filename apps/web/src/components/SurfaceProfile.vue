<script setup lang="ts">
import { computed } from 'vue'
import type { TerrainProfilePoint } from '../lib/terrainProfileTypes'
import type { SurfaceProfileSample, SurfaceProfileSource, SurfaceProfileSummary } from '../lib/surfaceProfileTypes'

const props = defineProps<{ summary?: SurfaceProfileSummary | null; source?: SurfaceProfileSource | null; profilePoints: TerrainProfilePoint[]; tripDate: string; inspectionReady?: boolean }>()
const emit = defineEmits<{ 'inspect-point': [chainage: number] }>()

type Display = { observedDate: string; age: number; resolution: number; samples: SurfaceProfileSample[] }
const classes: Record<number, { condition: SurfaceProfileSample['condition']; status: SurfaceProfileSample['status']; label: string }> = {
  2: { condition: 'shadow', status: 'partial', label: 'Тінь' }, 3: { condition: 'shadow', status: 'partial', label: 'Тінь від хмар' },
  4: { condition: 'vegetation', status: 'available', label: 'Рослинність' }, 5: { condition: 'not_vegetated', status: 'available', label: 'Без рослинності' },
  6: { condition: 'water', status: 'available', label: 'Клас води' }, 8: { condition: 'cloud', status: 'partial', label: 'Хмари' },
  9: { condition: 'cloud', status: 'partial', label: 'Хмари' }, 10: { condition: 'cloud', status: 'partial', label: 'Тонкі перисті хмари' },
  11: { condition: 'snow_ice', status: 'partial', label: 'Сніг / лід' },
}
function date(value: unknown) {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return null
  const parsed = new Date(`${value}T00:00:00Z`)
  return Number.isFinite(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value ? value : null
}
function instant(value: unknown) {
  if (typeof value !== 'string') return null
  const match = value.match(/^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d{1,6}))?Z$/)
  if (!match) return null
  const parsed = new Date(value), fraction = (match[2] || '').padEnd(6, '0')
  return Number.isFinite(parsed.getTime()) && parsed.toISOString() === `${match[1]}.${fraction.slice(0, 3)}Z` ? { date: parsed, key: `${match[1]}.${fraction}Z` } : null
}
function samePoint(left: unknown, right: unknown) { return !!left && !!right && typeof (left as any).longitude === 'number' && typeof (left as any).latitude === 'number' && (left as any).longitude === (right as any).longitude && (left as any).latitude === (right as any).latitude }
function sameSample(left: SurfaceProfileSample | null | undefined, right: SurfaceProfileSample) { return !!left && left.chainage_m === right.chainage_m && samePoint(left.requested_point, right.requested_point) && left.scl_class === right.scl_class && left.condition === right.condition && left.status === right.status }
function validSample(sample: any, point: TerrainProfilePoint) {
  if (!sample || !Number.isFinite(sample.chainage_m) || sample.chainage_m !== point.chainage_m || !samePoint(sample.requested_point, point.point) || !['available', 'partial', 'unavailable'].includes(sample.status) || !['unknown', 'vegetation', 'not_vegetated', 'water', 'cloud', 'shadow', 'snow_ice'].includes(sample.condition)) return false
  if (sample.scl_class === null) return sample.condition === 'unknown' && sample.status !== 'available'
  if (!Number.isInteger(sample.scl_class) || sample.scl_class < 0 || sample.scl_class > 11) return false
  const expected = classes[sample.scl_class]
  return expected ? sample.condition === expected.condition && sample.status === expected.status : sample.condition === 'unknown' && sample.status === 'partial'
}
function label(sample: SurfaceProfileSample) { return sample.scl_class === null ? 'Невідомо' : classes[sample.scl_class]?.label || 'Невідомо' }
const display = computed<Display | null>(() => {
  const summary = props.summary, source = props.source
  if (!summary || !source || summary.status === 'unavailable' || summary.basis !== 'sentinel2_l2a_scl_profile_points' || summary.coverage !== 'discrete_points' || summary.selection_scope !== 'bounded_catalogue_result' || !Array.isArray(summary.samples) || summary.samples.length < 2 || summary.samples.length > 81 || summary.samples.length !== props.profilePoints.length || !summary.samples.every((sample, index) => validSample(sample, props.profilePoints[index]))) return null
  const assessment = date(summary.assessment_date), observed = instant(summary.observed_at), retrieved = instant(summary.retrieved_at)
  const resolution = summary.resolution_m
  if (!assessment || assessment !== props.tripDate || !observed || !retrieved || observed.key > retrieved.key || observed.date.toISOString().slice(0, 10) > assessment || typeof summary.scene_id !== 'string' || !summary.scene_id || typeof resolution !== 'number' || !Number.isFinite(resolution) || resolution <= 0) return null
  const age = (Date.parse(`${assessment}T00:00:00Z`) - Date.parse(`${observed.date.toISOString().slice(0, 10)}T00:00:00Z`)) / 86400000
  if (!Number.isInteger(age) || age < 0 || summary.scene_age_days !== age || source.id !== 'sentinel-2-l2a' || source.extraction_scope !== 'spaced_scene_classification_points' || source.status !== summary.status || source.retrieved_at !== summary.retrieved_at || source.observed_at !== summary.observed_at || !/^sha256:[0-9a-f]{64}$/.test(source.content_sha256 || '') || summary.source_content_sha256 !== source.content_sha256 || source.data?.extraction_scope !== source.extraction_scope || source.data.assessment_date !== assessment || source.data.scene_id !== summary.scene_id || !Array.isArray(source.data.samples) || source.data.samples.length !== summary.samples.length || !source.data.samples.every((sample, index) => sameSample(sample, summary.samples[index]))) return null
  const aggregate = summary.samples.every(sample => sample.status === 'available') ? 'available' : 'partial'
  if (summary.status !== aggregate) return null
  return { observedDate: observed.date.toISOString().slice(0, 10), age, resolution, samples: summary.samples }
})
function count(value: number) { return `${value} ${value === 1 ? 'точка' : value < 5 ? 'точки' : 'точок'}` }
</script>

<template>
  <details class="surface-profile" aria-label="Супутник уздовж A → B">
    <summary>Супутник уздовж A → B <span v-if="display">· {{ display.observedDate }} · {{ count(display.samples.length) }}</span></summary>
    <template v-if="display">
      <p class="surface-meta">Sentinel-2 L2A · сцена {{ display.observedDate }} UTC · {{ display.age }} діб до обраної дати · рідна комірка {{ display.resolution }} м.</p>
      <div class="surface-samples" aria-label="Датовані класи сцени у точках профілю">
        <div v-for="sample in display.samples" :key="sample.chainage_m" data-testid="surface-sample"><span>{{ sample.chainage_m.toFixed(0).replace('.', ',') }} м</span><strong>{{ label(sample) }}</strong><button v-if="inspectionReady" data-testid="surface-inspect" type="button" :aria-label="`Оглянути точку на ${sample.chainage_m.toFixed(0)} м`" @click="emit('inspect-point', sample.chainage_m)">Оглянути</button></div>
      </div>
      <p class="surface-note">Це дискретні точки, не коридор між A і B. Класи сцени є датованими спостереженнями, не прогнозом умов на обрану дату. «Клас води» не встановлює затоплення чи брід; «Без рослинності» не означає суху або безхмарну поверхню.</p>
    </template>
    <p v-else class="surface-unknown">Дані супутника не узгоджено для цього профілю.</p>
  </details>
</template>

<style scoped>
.surface-profile{margin:10px 0;font-size:10px;color:var(--muted)}.surface-profile summary{cursor:pointer;color:var(--blue);font-size:11px}.surface-meta,.surface-note,.surface-unknown{line-height:1.5;margin:8px 0}.surface-samples{max-height:230px;overflow:auto;border:1px solid var(--line);border-radius:5px}.surface-samples>div{display:grid;grid-template-columns:58px minmax(0,1fr) auto;gap:7px;align-items:center;padding:6px;border-bottom:1px solid var(--line)}.surface-samples>div:last-child{border-bottom:0}.surface-samples strong{font-weight:600;color:var(--ink)}.surface-samples button{border:1px solid var(--line);border-radius:4px;background:#fff;color:var(--blue);font:inherit;padding:3px 5px}.surface-note{font-size:10px}
</style>
