<script setup lang="ts">
import { computed } from 'vue'
import { formatNumber, formatTime, localized } from '../lib/presentation'

type Step = { theta_1?: number | null; theta_2?: number | null }
type Scenario = { id: string; label_uk?: string; status?: string; steps?: Step[]; drying_confirmed_at?: string | null }
type Research = {
  status?: 'research_only' | 'abstained'
  model_version?: string
  condition?: string
  summary_uk?: string
  reason_codes?: string[]
  metrics?: { precipitation_mm?: number | null; et0_mm?: number | null; net_atmospheric_input_mm?: number | null; horizon_hours?: number | null; max_mass_residual_mm?: number | null }
  scenarios?: Scenario[]
  drying_window?: { kind?: string; earliest?: string | null; latest?: string | null; persistence_hours?: number | null; censored_scenarios?: number | null }
  assumptions_uk?: string[]
  source_refs?: unknown[]
}
const props = defineProps<{ research: Research | null | undefined }>()
const research = computed(() => props.research)
const reasonLabels: Record<string, string> = {
  CRITICAL_SOURCE_MISSING: 'Бракує обов’язкових вхідних даних.',
  FORCING_GAP: 'Пропуск погодних даних: використано лише повні послідовні інтервали.',
  INVALID_FORCING: 'Від’ємні опади або ET₀: вхідні дані відхилено.',
  FREEZE_THAW_AMBIGUOUS: 'Сніг, можливе замерзання або невідомий тепловий стан: теплий водний баланс не застосовано.',
  STATE_INITIALIZATION_UNAVAILABLE: 'Немає допустимого початкового модельного стану профілю.',
  INSUFFICIENT_COMPLETE_HORIZON: 'Немає щонайменше 24 годин повних послідовних вхідних даних.',
  MODEL_NUMERICAL_FAILURE: 'Числова перевірка балансу не пройдена; результат не видано.',
  SCENARIO_UNAVAILABLE: 'Не всі гідравлічні сценарії доступні; узагальнений стан невідомий.',
  missing_forcing: 'Немає достатніх метеорологічних вхідних даних.',
  missing_weather: 'Бракує метеорологічних даних для розрахунку.',
  missing_weather_data: 'Бракує метеорологічних даних для розрахунку.',
  missing_initial_state: 'Неможливо встановити початковий стан профілю.',
  invalid_forcing: 'Вхідні метеорологічні дані не пройшли перевірку.',
  horizon_unavailable: 'Горизонт розрахунку недоступний.',
}
function reason(code: string) { return reasonLabels[code] || localized(code) }
function finalStep(scenario: Scenario) { return scenario.steps?.at(-1) }
function dryingTime(scenario: Scenario) {
  return scenario.drying_confirmed_at ? `${formatTime(scenario.drying_confirmed_at)} UTC` : 'Не підтверджено в межах горизонту'
}
function windowText(window: Research['drying_window']) {
  if (!window) return 'Недоступно'
  if (window.kind === 'scenario_bounds' && (window.censored_scenarios || 0) > 0) return `Найраніше серед завершених сценаріїв: ${window.earliest ? formatTime(window.earliest) + ' UTC' : '—'}. Верхню межу не встановлено: ${formatNumber(window.censored_scenarios, 0)} ${window.censored_scenarios === 1 ? 'сценарій не підтвердив' : 'сценарії не підтвердили'} критерій у межах горизонту`
  if (window.kind === 'scenario_bounds' && window.earliest && window.latest) return `${formatTime(window.earliest)} – ${formatTime(window.latest)} UTC; стійкість ${formatNumber(window.persistence_hours, 0)} год`
  if (window.kind === 'not_reached') return 'Не досягнуто в межах горизонту'
  return 'Недоступно'
}
</script>

<template>
  <section v-if="research" class="research-assessment" data-testid="research-assessment">
    <h3>Дослідницький водний баланс</h3>
    <p v-if="research.status === 'research_only'"><b>{{ localized(research.condition || 'unknown') }}</b> · {{ research.summary_uk || 'Підсумок не надано.' }}</p>
    <p v-else-if="research.status === 'abstained'" role="status"><b>Оцінка недоступна</b><span v-if="research.reason_codes?.length">: {{ research.reason_codes.map(reason).join(' ') }}</span></p>
    <template v-if="research.status === 'research_only'">
      <p v-if="research.reason_codes?.length" class="warning">{{ research.reason_codes.map(reason).join(' ') }}</p>
      <p>Опади: {{ formatNumber(research.metrics?.precipitation_mm, 1) }} мм<br>ET₀: {{ formatNumber(research.metrics?.et0_mm, 1) }} мм<br>Чистий атмосферний приплив: {{ research.metrics?.net_atmospheric_input_mm != null && research.metrics.net_atmospheric_input_mm > 0 ? '+' : research.metrics?.net_atmospheric_input_mm != null && research.metrics.net_atmospheric_input_mm < 0 ? '−' : '' }}{{ formatNumber(research.metrics?.net_atmospheric_input_mm == null ? null : Math.abs(research.metrics.net_atmospheric_input_mm), 1) }} мм<br>Горизонт: {{ formatNumber(research.metrics?.horizon_hours, 0) }} год<br>Максимальний залишок масового балансу: {{ formatNumber(research.metrics?.max_mass_residual_mm, 3) }} мм</p>
      <div v-if="research.scenarios?.length" class="feature-scroll"><table>
        <thead><tr><th>Сценарій</th><th>θ 0–10 см</th><th>θ 10–30 см</th><th>Умовне висихання</th></tr></thead>
        <tbody><tr v-for="scenario in research.scenarios" :key="scenario.id"><td>{{ scenario.label_uk || scenario.id }}</td><td>{{ formatNumber(finalStep(scenario)?.theta_1) }}</td><td>{{ formatNumber(finalStep(scenario)?.theta_2) }}</td><td>{{ dryingTime(scenario) }}</td></tr></tbody>
      </table></div>
      <p>Вікно умовного висихання: {{ windowText(research.drying_window) }}.</p>
      <details><summary>Припущення та джерела</summary><p>Профіль 0–10 / 10–30 см — дослідницьке припущення, а не фактичний вимір 0–1 см від постачальника.</p><ul v-if="research.assumptions_uk?.length"><li v-for="assumption in research.assumptions_uk" :key="assumption">{{ assumption }}</li></ul><p v-if="research.source_refs?.length">Посилань на джерела: {{ research.source_refs.length }}.</p><p>Зміна повної маси не змінює цей водний баланс: транспортну межу та модель впливу коліс не застосовано.</p></details>
    </template>
    <p class="warning">Проїзд не оцінено. Умовне висихання не є часом відкриття дороги.</p>
  </section>
</template>
