// @vitest-environment jsdom
import { createApp, h, nextTick, reactive } from 'vue'
import { expect, it } from 'vitest'
import WeatherDayConditions from './WeatherDayConditions.vue'
import type { WeatherDaySummary } from '../lib/weatherDayTypes'
import type { AntecedentPrecipitationSummary } from '../lib/antecedentPrecipitationTypes'

it('embeds prior-day precipitation in the existing weather card and withdraws it on date change', async () => {
  const summary: WeatherDaySummary = {date:'2026-10-26',timezone:'UTC',basis:'weather_model_not_field_observation',status:'available',
    precipitation:{status:'available',total_mm:2.1,known_intervals:24,expected_intervals:24},
    soil_temperature:{status:'available',min_c:4,max_c:9,known_samples:24,expected_samples:24,at_or_below_zero_samples:0},
    snow_depth:{status:'available',min_m:0,max_m:0,known_samples:24,expected_samples:24}}
  const days: AntecedentPrecipitationSummary['days'] = Array.from({length:7},(_,i)=>({date:`2026-10-${19+i}`,status:'available',total_mm:1,known_intervals:24,expected_intervals:24}))
  const antecedent: AntecedentPrecipitationSummary = {date:'2026-10-26',timezone:'UTC',basis:'weather_model_not_field_observation',window_start:'2026-10-19',window_end_exclusive:'2026-10-26',window_days:7,status:'available',total_mm:7,known_intervals:168,expected_intervals:168,days}
  const props = reactive({summary,antecedent,tripDate:'2026-10-26'})
  const root = document.createElement('div'), app = createApp({ render: () => h(WeatherDayConditions, props) })
  app.mount(root)
  try {
    await nextTick()
    expect(root.querySelector('.weather-day')?.textContent).toContain('Опади до поїздки')
    expect(root.textContent).toContain('7,0 мм')
    expect(root.querySelector('.day-precipitation')?.textContent).toContain('2,1 мм')
    props.tripDate = '2026-10-27'; await nextTick()
    expect(root.textContent).not.toContain('7,0 мм')
    expect(root.textContent).toContain('Немає узгоджених даних')
  } finally { app.unmount() }
})
