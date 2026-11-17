# V15 — dated model soil-water context

## Product decision

Original well-access request (`inputs/user-requirements-extract.md:7-17,25-33,57`) asks about after-rain/thaw conditions with automatic environmental inputs. Accepted design (`design/route-planner-v2/DESIGN.md:19-26,33`) separates dated conditions from static cover. V14 still puts an uncounted 0–1cm model range among reference terrain facts; the already captured 1–3cm and3–9cm variables are absent from the inspector. Put validated dated model water content beside weather, inside a closed native disclosure. Do not add another workflow or model.

This does not provide measured surface wetness, saturation, waterlogging, water table, flood detection, bearing capacity, vehicle limits, a passability score or a drying/opening date. Existing unknowns stay visible. Norway remains the non-operational public reference.

## Source and native preflight

- Existing fixed `icon_global`/Open-Meteo request already captures `soil_moisture_0_to_1cm`, `soil_moisture_1_to_3cm`, `soil_moisture_3_to_9cm`, unit `m³/m³`, in the internal research DTO. No provider/request/variable/window/registry/cache/budget changes.
- Publisher documentation: https://open-meteo.com/en/docs/dwd-api explicitly lists those three depth intervals. They are supplied model layers, not local measurements or a new combined0–9cm value. Do not remap/average/normalize them or convert them to a saturation percentage.
- The same publisher page states that ICON Global output after78 forecast hours is interpolated from3-hourly to hourly. `24/24` therefore measures completeness of the exported hourly API series, not24 independent native outputs or field observations. Include a short interpolation/completeness limitation inside the disclosure; do not claim native hourly resolution.
- Existing exact source bytes SHA256 `4ef282407d6e88b8414b9381349b45c8c1feb3a82988416697e83db9decda4b4`, selected UTC day2026-10-26: 24 samples each; ranges0.296–0.340,0.298–0.339,0.306–0.341 m³/m³. Requested59.98500020992624,10.733331822658165; returned model grid60,10.75. This preflight is a replay of captured bytes, not a fresh observation or validation of local wetness.

## Backend contract

New pure helper `apps/api/model_soil_water.py`, function `summarize_model_soil_water(dto, trip_date)`. Off-road `_weather(...include_antecedent=True)` adds `weather.soil_water` from the same DTO before internal research rows are discarded. Road payload/rendering stay unchanged. Existing `day_summary`, `outlook`, `antecedent_precipitation`, weather status and source digest are unchanged.

`soil_water` has:

- `date`: strict selected ISO date or null; `timezone: "UTC"`; `basis: "weather_model_not_field_observation"`; aggregate `status` available/partial/unavailable.
- `source_id`, `model`, `source_sha256`: literal `open-meteo-icon-global`, `icon_global`, original `sha256:` plus64 lower-case hex, or null if outer binding is invalid. `unit: "m³/m³"`.
- `requested_point`, `grid_point`: finite WGS84 latitude/longitude only, or null. Grid point is distinct from the chosen line point. Never substitute one for the other.
- Exactly three ordered `layers`: `{variable,from_cm,to_cm,status,min_m3_m3,max_m3_m3,known_samples,expected_samples:24}` for0–1,1–3,3–9cm. Min/max cover known valid instantaneous samples, not an inferred continuous day; null if none.

Require original assessment-date binding, exact source/model/digest and valid requested/grid points before using values. Use internal `research_series`, otherwise existing `series`; inspect at most256 rows (normal research DTO≤73). An over-budget/non-list input is unknown, never a truncated valid prefix. Do not mutate the DTO.

Use selected UTC-day00..23 instantaneous timestamps, each exactly once and at whole hours. Ignore other days/offsets/malformed times; duplicate equivalent UTC timestamps make that slot unknown. A missing/bad-unit layer fails locally. Accept only finite non-boolean numbers in[0,1]; zero is a real value, not NoData or a dry/passable label. Null/string/bool/negative/>1/NaN/Inf/overflow become unknown for that layer/hour. Counts0/1..23/24 imply unavailable/partial/available; aggregate available iff all three available, unavailable iff all unavailable, otherwise partial. Handle calendar bounds without overflow. Strict JSON always.

No new endpoint, source IO, weather fetch, admission worker or cache. Preserve V14 exact selected point, legacy midpoint/road requests, CSRF/Origin/ownership/body limits and source budgets.

## Frontend contract

New `ModelSoilWater.vue`, matching types/tests; integrate only in the off-road weather card after the existing history/outlook, as a closed native disclosure `Модельна вода в ґрунті`. Pass current actual `selectedPoint` and weather-source digest through `WeatherDayConditions` to bind date/point/digest before rendering numbers. Reject malformed source/model/unit/date/point/digest/layer order/depth/count/status/range or aggregate mismatch, including empty available. Null/missing/out-of-range remains unknown.

Show three source-provided depth intervals, raw m³/m³ ranges (3 decimal display), known/24 hourly samples and partial wording (`серед відомих точок`, not full-day extrema). Identify ICON Global via Open-Meteo/model grid and distinguish it from the requested point. Explicitly state this is model volumetric water content, not measured local surface wetness, saturation, bearing capacity or permission to drive. No inferred classes, traffic-light colours or local spatial-resolution claim.

Hide the old standalone off-road0–1cm range from the reference terrain disclosure to avoid two inconsistent presentations; preserve its existing road branch exactly. Use existing point/revision invalidation. Opening the new disclosure issues zero requests. Do not move selected-day rain/history lower, change A/B/date/vehicle inputs, create a new screen/layer, or request a new profile. Mobile stays one sheet with no horizontal overflow.

## Acceptance

1. TDD pure helper: exact three native layers, UTC/duplicate/cap/unit/value/calendar faults, zero versus null, partial counts, immutable DTO, strict JSON and source/point/date/digest binding. Endpoint test proves one existing weather call, same source digest/point and unchanged road/guards.
2. Frontend tests: correct/zero/partial/unknown, malformed and empty available fail closed, exact actual-point/date/digest binding, one closed native disclosure, no request on open, old off-road duplicate removed/road unchanged, stale selection/date/mass clearing.
3. Parent full suites/typecheck/build/audit. Stage outside dist until coherent publication; preserve existing warnings. Public/native replay checks selected point and final available forecast day against exact captured raw source bytes/digest. No fabricated fallback.
4. Actual desktop/mobile screenshots and bounds against design: selected-day rain position preserved and wholly visible at390×844; native keyboard disclosure/zero requests; real V14 point switch and trip edits clear old data. Public assets/health/source hashes verified and clean browser restored.
5. One consolidated independent review; only one bounded corrective batch/final check if a practical defect appears. Full product is not complete.
