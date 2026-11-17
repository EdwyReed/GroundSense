# V10 — precipitation before the trip date

## Fit to the original request and design

The original well-access request asks about fields/forest after rain or during thaw. A selected-day weather total alone omits preceding precipitation. Keep the existing A/B/date/vehicle map-first screen and add a compact prior-seven-day precipitation block inside the existing weather card, with daily values in a disclosure. No new input, map layer, route recommendation, drying-time estimate or separate workflow.

## Verified source semantics

Open-Meteo documents Past Days as recently archived forecasts, not field observations. Precipitation is the sum of the preceding hour and includes rain, showers and snow.[1] The real control-point request with `models=icon_global`, `past_days=7`, `forecast_days=7`, UTC and the existing variables returned336 rows from2026-10-19T00:00 through2026-11-01T23:00,22529 bytes, mm and no null precipitation. Raw receipt `qa/route-v2/wakeup14-native-weather-history.json`. This wire probe establishes availability at the control point only.

## Backend scope

- Add opt-in `LiveWeatherClient.forecast_for_section(latitude, longitude, assessment_date)` using the existing fixed endpoint/model/variables plus `past_days=7`. Exactly one provider request, never a second history request. Preserve the old `forecast` request/cache/DTO and research72h semantics for existing callers.
- Use a separate bounded cache namespace from legacy forecast entries, same5min/64 indexes and preserved source snapshots/digests. Section wire response streamed≤1MiB and≤400 hourly rows, redirect disabled, existing timeout and strict unit/finite/time checks. Constructor network-free. Source issue time stays unknown; do not relabel archived forecasts as observations/reanalysis.
- Opt-in DTO adds `antecedent_series`: only preceding 7-day hourly interval rows up to selected midnight (at most 169 including the excluded earliest 00 boundary); each row has UTC `time`, `precipitation`, `precipitation_interval_start/end`. Strictly increasing whole-hour UTC timestamps enforce this bound; sub-hourly input is rejected. Existing selected-day series and research72h selection remain unchanged.
- Pure `summarize_antecedent_precipitation(dto, trip_date)` in `apps/api/antecedent_precipitation.py` binds to selected date, consumes≤200 rows without trusting a valid prefix of an over-budget tail, and never mutates input. Strict finite/nonnegative mm; duplicates, missing/null/negative/wrong-interval rows stay unknown. Seven UTC days D−7 through D−1 require intervals ending01..next00; exclude D−7T00, include DT00, exclude DT01 and later. No partial sum presented as a total, no fraction normalization. Preserve valid daily totals when another day is incomplete. Overflow gives null, never Inf/NaN.
- Parent integrates only the off-road context weather lane, falling back to existing forecast test doubles. Public response includes summary only, not raw antecedent/research rows. Existing road path, guards, budgets, lanes, source-point and stale binding unchanged.

## Summary DTO

`weather.antecedent_precipitation`:

- `date`: selected ISO date; `timezone`:UTC; `basis`:weather_model_not_field_observation.
- `window_start`: ISO date D−7; `window_end_exclusive`: selected ISO date; `window_days`:7.
- `status`:available/partial/unavailable; `total_mm`:number only for complete finite168-interval total, otherwise null; `known_intervals`:0..168; `expected_intervals`:168.
- `days`: exactly7 chronological objects `{date,status,total_mm,known_intervals,expected_intervals:24}`. Each total exists only for24 correct intervals and finite sum. Nonempty known data with an unavailable total is partial; zero known is unavailable.
- Invalid/unbound input: date/window derived only from a valid requested ISO date, seven unavailable rows if date valid; null date/window and empty days if invalid or the seven-day window cannot be represented by the calendar. Nonrepresentable numeric intervals stay unknown without hiding other valid daily totals. No guessed values or source substitution.

## UI scope

`AntecedentPrecipitation.vue` accepts `{summary,tripDate}`, type exported by `lib/antecedentPrecipitationTypes.ts`. Parent embeds it in `WeatherDayConditions` with optional `antecedent` prop. Headline “Опади до поїздки”, explicit7 prior UTC dates, total or unknown and known/168. Disclosure “Добові суми” shows7 actual daily totals/counts. Strictly validate numeric/date/window/count/day consistency, no numeric strings, invalid dates or stale totals. Keep partial day totals visible without a false weekly total. No graph, external request, warning color as mobility judgment, or expanded daily table by default.

Copy must say model values may include a forecast depending on selected date, and precipitation is not measured soil wetness or passability. Source/provider remains visible in existing disclosure. Props/date/section revision clearing remains parent-owned and tested.

## Acceptance

RED→GREEN for real prior7-day/selected-day/research coexistence, one request plus cache isolation, bounded wire/rows, preceding-hour/duplicate/partial/unit/overflow summaries and actual rendered component. Independently replay168 raw provider interval values and7 daily sums against public summary and exact source digest. Verify earliest/last forecast day and future selected date, old weather-day behavior, guards and registry. Check desktop/mobile screenshots, disclosure without a new request, section/date clearing and preservation of map-first layout. No complete-product claim.

## Sources

[1] https://open-meteo.com/en/docs/dwd-api
