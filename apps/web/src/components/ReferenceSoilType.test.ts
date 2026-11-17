// @vitest-environment jsdom
import { createApp, nextTick } from 'vue'
import { expect, it } from 'vitest'
import ReferenceSoilType from './ReferenceSoilType.vue'
import type { SoilTypeData } from '../lib/soilTypeTypes'

const point = { longitude: 10.733331822658165, latitude: 59.98500020992624 }
const valid = (): SoilTypeData => ({
  status: 'available',
  basis: 'hwsd_v2_smu_dominant_soil',
  requested_point: { latitude: point.latitude, longitude: point.longitude },
  map_unit_id: 10124,
  wrb_code: 'PZal',
  wrb_name: 'Albic Podzols',
  share_percent: 70,
  resolution_arc_seconds: 30,
  temporal_scope: 'static_reference',
  classification_system: 'WRB 2022',
  spatial_scope: 'soil_mapping_unit',
})

async function mount(soilType: unknown, selectedPoint = point) {
  const root = document.createElement('div')
  const app = createApp(ReferenceSoilType, { soilType, selectedPoint })
  app.mount(root); await nextTick()
  return { root, app }
}

it('renders native WRB identity and the map-unit share without treating either as a point measurement', async () => {
  const { root, app } = await mount(valid())
  try {
    expect(root.textContent).toContain('Довідковий тип ґрунту')
    expect(root.textContent).toContain('Albic Podzols · WRB PZal')
    expect(root.textContent).toContain('Домінантний тип у картографічній одиниці 10124')
    expect(root.textContent).toContain('70% одиниці, не ймовірність у цій точці')
    expect(root.textContent).toContain('HWSD2.0 · WRB 2022 · 30″ (≈1 км) · статична карта')
    expect(root.textContent).toContain('Склад одиниці може бути неоднорідним. Не польова проба, не поточна вологість і не несуча здатність.')
    expect(root.textContent).not.toMatch(/проїзн|несуч.*оцінен/i)
  } finally { app.unmount() }
})

it.each([
  ['missing', undefined],
  ['wrong basis', { ...valid(), basis: 'soilgrids' }],
  ['wrong static identity', { ...valid(), temporal_scope: 'observation' }],
  ['wrong nomenclature', { ...valid(), classification_system: 'WRB 2021' }],
  ['wrong spatial scope', { ...valid(), spatial_scope: 'point' }],
  ['point mismatch', { ...valid(), requested_point: { latitude: point.latitude, longitude: 10.7 } }],
  ['non-native resolution', { ...valid(), resolution_arc_seconds: 250 }],
  ['invalid map unit', { ...valid(), map_unit_id: 0 }],
  ['invalid share', { ...valid(), share_percent: 101 }],
  ['partial available fields', { ...valid(), status: 'partial' }],
])('shows unknown rather than translating malformed or stale data: %s', async (_name, soilType) => {
  const { root, app } = await mount(soilType)
  try {
    expect(root.textContent).toContain('Тип ґрунту за довідковою картою невідомий.')
    expect(root.textContent).not.toContain('Albic Podzols')
    expect(root.textContent).not.toContain('10124')
  } finally { app.unmount() }
})

it('may retain only a valid partial map unit while leaving the class and share unknown', async () => {
  const { root, app } = await mount({ ...valid(), status: 'partial', wrb_code: null, wrb_name: null, share_percent: null })
  try {
    expect(root.textContent).toContain('Картографічна одиниця 10124 відома; тип ґрунту невідомий.')
    expect(root.textContent).toContain('Частка домінантного типу невідома.')
    expect(root.textContent).not.toContain('Albic Podzols')
    expect(root.textContent).not.toContain('70%')
  } finally { app.unmount() }
})

it('does not turn the WRB nomenclature year into an observation date or make mobility claims', async () => {
  const { root, app } = await mount(valid())
  try {
    expect(root.textContent).toContain('WRB 2022')
    expect(root.textContent).toContain('статична карта')
    expect(root.textContent).not.toMatch(/спостереження 2022|дата спостереження|проїзність оцінено/i)
  } finally { app.unmount() }
})
