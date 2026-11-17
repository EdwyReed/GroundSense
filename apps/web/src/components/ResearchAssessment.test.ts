// @vitest-environment jsdom
import { createApp } from 'vue'
import { afterEach, describe, expect, it } from 'vitest'
import ResearchAssessment from './ResearchAssessment.vue'

const mounted: HTMLElement[] = []
function render(research: any) {
  const root = document.createElement('div')
  document.body.append(root)
  mounted.push(root)
  const app = createApp(ResearchAssessment, { research })
  app.mount(root)
  return root
}
afterEach(() => { while (mounted.length) mounted.pop()?.remove() })

describe('ResearchAssessment', () => {
  it('shows a research water-balance result without presenting it as road access', () => {
    const root = render({
      status: 'research_only', model_version: 'live-warm-water/1', condition: 'less_adverse',
      summary_uk: 'Опади нижчі за випаровування.', reason_codes: [],
      metrics: { precipitation_mm: 4.2, et0_mm: 7.1, net_atmospheric_input_mm: -2.9, horizon_hours: 72, max_mass_residual_mm: 0.004 },
      scenarios: [
        { id: 'dry', label_uk: 'Сухіше', status: 'available', steps: [{ state: { H: 1, L1: 2, L2: 3 }, theta_1: .21, theta_2: .27 }], drying_confirmed_at: '2026-10-28T12:00:00Z' },
        { id: 'central', label_uk: 'Базовий', status: 'available', steps: [{ state: { H: 1, L1: 2, L2: 3 }, theta_1: .23, theta_2: .29 }], drying_confirmed_at: null },
        { id: 'wet', label_uk: 'Вологіше', status: 'available', steps: [{ state: { H: 1, L1: 2, L2: 3 }, theta_1: .25, theta_2: .31 }], drying_confirmed_at: null },
      ],
      drying_window: { kind: 'scenario_bounds', earliest: '2026-10-28T12:00:00Z', latest: '2026-10-29T00:00:00Z', persistence_hours: 12, censored_scenarios: 2 },
      assumptions_uk: ['Профіль 0–10 / 10–30 см є дослідницьким припущенням.'], source_refs: [],
    })
    expect(root.textContent).toContain('Дослідницький водний баланс')
    expect(root.textContent).toContain('Опади: 4,2 мм')
    expect(root.textContent).toContain('ET₀: 7,1 мм')
    expect(root.textContent).toContain('Чистий атмосферний приплив: −2,9 мм')
    expect(root.textContent).toContain('Горизонт: 72 год')
    expect(root.textContent).toContain('Сухіше')
    expect(root.textContent).toContain('0,21')
    expect(root.textContent).toContain('28.10.2026')
    expect(root.textContent).toContain('Проїзд не оцінено')
    expect(root.textContent).toContain('не є часом відкриття дороги')
    expect(root.textContent).toContain('Верхню межу не встановлено')
    expect(root.textContent).toContain('2 сценарії')
    expect(root.textContent).not.toContain('Безпечно для вантажівки')
  })
  it('translates abstention reasons and does not substitute missing metrics with zero', () => {
    const root = render({ status: 'abstained', reason_codes: ['missing_weather_data'], metrics: {} })
    expect(root.textContent).toContain('Бракує метеорологічних даних для розрахунку.')
    expect(root.textContent).not.toContain('Опади: 0 мм')
    expect(root.textContent).toContain('Проїзд не оцінено')
  })
  it('translates the actual scientific engine reason codes', () => {
    const root = render({ status: 'abstained', reason_codes: ['FORCING_GAP', 'FREEZE_THAW_AMBIGUOUS', 'INSUFFICIENT_COMPLETE_HORIZON'] })
    expect(root.textContent).toContain('Пропуск')
    expect(root.textContent).toContain('замерзання')
    expect(root.textContent).not.toContain('FORCING_GAP')
    expect(root.textContent).not.toContain('FREEZE_THAW_AMBIGUOUS')
    expect(root.textContent).not.toContain('INSUFFICIENT_COMPLETE_HORIZON')
  })
})
