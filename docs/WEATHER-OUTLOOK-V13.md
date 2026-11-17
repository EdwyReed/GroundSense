# V13 — compare weather after the selected trip date

## Why this slice

The original request asks about conditions after rain/thaw and when to plan a trip (`inputs/user-requirements-extract.md:7,25,29`). The accepted design keeps A/B/date/vehicle and all essential actions on the map. The current section response shows only the selected day's weather; comparing another date requires editing the trip and reanalysis. Its already captured `research_series` contains up to73 hourly endpoints through selected midnight+72h. Expose two subsequent daily summaries inside the existing weather card, without another request or a new screen.

Fresh real preflight `qa/route-v2/wakeup17-native-outlook-before.json` independently reads the current context's exact Open-Meteo snapshot:2026-10-27 has24 precipitation intervals/14.7mm;2026-10-28 has24/0mm. Both have model surface temperature/snow samples. These are available model inputs, not field measurements or a prediction of when a truck can pass. No dry-day recommendation, ranking, admissible mass or recovery-time calculation.

## Boundaries

- Reuse the same captured DTO/source digest and existing `summarize_weather_day` semantics; do not modify `LiveWeatherClient`, request shape, cache identity, source budgets, worker lanes or endpoints.
- Terrain/off-road only. Legacy road context/presentation stays unchanged.
- No new input, layer, auto-reanalysis, date-selection control or route recommendation. A native collapsed disclosure `Наступні 2 дні · погода` follows existing antecedent precipitation within `WeatherDayConditions`.
- Keep chosen-day weather/history first. Keep terrain details, visible mobility/current-water/clearance unknowns, model disclaimers and static reference data intact.
- Use UTC calendar days. Precipitation totals need24 preceding-hour intervals ending01..next00; model surface temperature and snow use00..23. Last horizon day may have23 rain intervals and a null total while temperature/snow remain known. Unknown does not mean zero or dry.

## Backend

New pure `apps/api/weather_outlook.py`: `summarize_weather_outlook(dto, trip_date)`. Return `{date,timezone:'UTC',basis:'weather_model_not_field_observation',horizon_days:2,status,days}`; `days` contains at most two existing WeatherDaySummary objects, strictly trip_date+1,+2, in order. Validate the original DTO assessment_date before deriving rebased daily views; never mutate DTO or expose raw research rows. Bound raw input by the existing256-row summarizer cap. Invalid binding/schema/over-budget input gives unavailable with empty days. Calendar overflow must safely stop without erasing an already representable prefix; an unrepresentable daily end yields an unknown day, never an exception or a fabricated date. Metric-local unit/value faults remain local. Aggregate status is available only for two complete available days, unavailable if no day has data, otherwise partial.

Parent integrates `weather.outlook` only for off-road `_weather(...include_antecedent=True)`, from the same fetched DTO. Existing day/history fields and source metadata stay unchanged. No extra provider request. Safe scalar conversion in the shared day summarizer must reject overflowing integers rather than discarding unrelated available metrics.

## Frontend

`WeatherOutlook.vue` props `outlook:WeatherOutlookData|null|undefined`, `tripDate:string`. DTO type reuses WeatherDaySummary. Validate strict date/basis/timezone/horizon, ordered next-day prefix (0..2), no duplicates/extra days and well-formed metric statuses/counts/finite bounds before showing a metric. Invalid outer binding/shape shows unknown; malformed metric does not poison an independent valid metric. Available precipitation requires24/24;23/24 or null/overflow total is unknown. Partial instantaneous ranges may show only with valid nonzero counts, clearly labelled incomplete. Never print NaN/Infinity or malformed raw strings.

Use native `<details class="weather-outlook">` initially closed. Each day shows date, precipitation, model surface temperature/snow and coverage counts. Explain: model forecast is not a drying/access estimate; the model horizon can be shorter; missing data do not mean dry ground. No requests or events. Parent mounts once inside existing weather card after history and only if the bound off-road response contains outlook.

## Acceptance

- Observe RED→GREEN pure/fetch-count/road/invalidation/component regressions, including duplicate/end-of-horizon/missing units/overflow/calendar cases and no DTO mutation.
- Full backend/frontend suites, typecheck/build/audit and diff check.
- Independent raw-snapshot replay for current and final available forecast date; partial future horizon must remain unknown without substituting another date.
- Fresh desktop1688×1003/mobile390×844 screenshots; native disclosure adds0 requests, same3 per analysis, map-marker selection clears old outlook, date/mass edit clears all stale evidence. Weather/history priority and one mobile sheet remain intact.
- Public assets match build; no registry assets or suitability records created. One consolidated review and a bounded corrective pass if required. Full product remains incomplete.
