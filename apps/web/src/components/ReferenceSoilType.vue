<script setup lang="ts">
import { computed } from 'vue'
import type { LngLat } from '../lib/routeTypes'
import type { SoilTypeData } from '../lib/soilTypeTypes'

const props = defineProps<{ soilType?: SoilTypeData | null; selectedPoint: LngLat }>()

type Display =
  | { kind: 'available'; mapUnitId: number; code: string; name: string; share: number }
  | { kind: 'partial'; mapUnitId: number }
  | { kind: 'unknown' }

const finite = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value)
const validMapUnit = (value: unknown): value is number => typeof value === 'number' && Number.isInteger(value) && value > 0 && value <= 2_147_483_647
const validCode = (value: unknown): value is string => typeof value === 'string' && /^[A-Za-z0-9]{1,16}$/.test(value)
const validName = (value: unknown): value is string => typeof value === 'string' && /^[A-Za-z][A-Za-z -]{0,127}$/.test(value) && value.trim() === value
const validShare = (value: unknown): value is number => finite(value) && value > 0 && value <= 100

const display = computed<Display>(() => {
  const soil = props.soilType
  if (!soil || !finite(props.selectedPoint.latitude) || !finite(props.selectedPoint.longitude)) return { kind: 'unknown' }
  if (soil.basis !== 'hwsd_v2_smu_dominant_soil' || soil.temporal_scope !== 'static_reference' || soil.classification_system !== 'WRB 2022' || soil.spatial_scope !== 'soil_mapping_unit' || soil.requested_point?.latitude !== props.selectedPoint.latitude || soil.requested_point?.longitude !== props.selectedPoint.longitude || !validMapUnit(soil.map_unit_id) || soil.resolution_arc_seconds !== 30) return { kind: 'unknown' }
  if (soil.status === 'available') {
    if (!validCode(soil.wrb_code) || !validName(soil.wrb_name) || !validShare(soil.share_percent)) return { kind: 'unknown' }
    return { kind: 'available', mapUnitId: soil.map_unit_id, code: soil.wrb_code, name: soil.wrb_name, share: soil.share_percent }
  }
  if (soil.status !== 'partial' || soil.wrb_code !== null || soil.wrb_name !== null || soil.share_percent !== null) return { kind: 'unknown' }
  return { kind: 'partial', mapUnitId: soil.map_unit_id }
})

function percent(value: number) { return `${String(value).replace('.', ',')}%` }
</script>

<template>
  <section class="reference-soil-type" :class="`is-${display.kind}`" aria-label="Довідковий тип ґрунту">
    <h4>Довідковий тип ґрунту</h4>
    <template v-if="display.kind === 'available'">
      <p class="soil-identity">{{ display.name }} · WRB {{ display.code }}</p>
      <p class="soil-detail">Домінантний тип у картографічній одиниці {{ display.mapUnitId }}</p>
      <p class="soil-detail">{{ percent(display.share) }} одиниці, не ймовірність у цій точці</p>
    </template>
    <template v-else-if="display.kind === 'partial'">
      <p class="soil-unknown">Картографічна одиниця {{ display.mapUnitId }} відома; тип ґрунту невідомий.</p>
      <p class="soil-detail">Частка домінантного типу невідома.</p>
    </template>
    <p v-else class="soil-unknown">Тип ґрунту за довідковою картою невідомий.</p>
    <p class="soil-meta">HWSD2.0 · WRB 2022 · 30″ (≈1 км) · статична карта</p>
    <p class="soil-note">Склад одиниці може бути неоднорідним. Не польова проба, не поточна вологість і не несуча здатність.</p>
    <p class="soil-note">Комерційне повторне використання: не встановлено.</p>
  </section>
</template>

<style scoped>
.reference-soil-type{padding:10px;background:#f7f9fc;border-radius:6px;margin:10px 0;border-left:4px solid #9aa3ad}.reference-soil-type.is-available{border-left-color:#7a8f62}.reference-soil-type.is-partial{border-left-color:#9a8254}.reference-soil-type h4{font-size:12px;margin:0 0 7px}.soil-identity{font-size:12px;font-weight:700;margin:0}.soil-detail,.soil-meta,.soil-note,.soil-unknown{font-size:10px!important;line-height:1.45!important;color:var(--muted);margin:6px 0 0!important}.soil-detail{color:var(--ink)}
</style>
