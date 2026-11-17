# Selected-day weather conditions — route-first increment

## Goal

The original requirements ask for selected-date effects after rain and during snow/thaw, primarily off-road well access. Existing cards show air temperature and shallow model moisture but hide available precipitation, snow depth and soil-surface temperature. Expose these existing model inputs inside the selected-section inspector, preserving `design/route-planner-v2/DESIGN.md`; no new screen, manual soil form, research balance or vehicle score.

## Pure backend summary

Add `apps/api/weather_day.py` with `summarize_weather_day(dto, trip_date)`. It makes no I/O and does not alter the raw DTO. Parent calls it inside `RouteContext._weather` while the full provider DTO is available, then puts the result in `weather.day_summary`; do not expose the full research_series or change the provider request/cache.

Return:
- `date`, `timezone:"UTC"`, `status:available|partial|unavailable`, `basis:"weather_model_not_field_observation"`;
- `precipitation:{status,total_mm:number|null,known_intervals:int,expected_intervals:24}`;
- `soil_temperature:{status,min_c:number|null,max_c:number|null,known_samples:int,expected_samples:24,at_or_below_zero_samples:int}`;
- `snow_depth:{status,min_m:number|null,max_m:number|null,known_samples:int,expected_samples:24}`.

Require `dto.assessment_date == trip_date`, a strict YYYY-MM-DD date, expected units (`mm`, `°C`, `m`) per metric and valid UTC timestamps. Use existing `research_series` if it is a list, otherwise `series`, at most256 rows; reject an oversized series instead of declaring a valid prefix complete while leaving possible duplicates uninspected. Index only relevant UTC timestamps; reject duplicate timestamps within the relevant00..next00 window rather than selecting a convenient duplicate. Ignore rows outside that window. Input faults, including a missing/wrong unit for one variable, remain local to the affected metric; no synthetic zero values. Reject booleans, non-finite numbers, negative rain/snow depths; preserve real zero and negative soil temperatures.

Instantaneous soil temperature/snow depth use the24 expected hourly points00..23 of the selected UTC date. Min/max describe only available model samples; partial ranges remain visibly partial. Zero-temperature count counts available samples≤0°C, not continuously frozen hours or a frozen ground layer.

Precipitation uses24 preceding-hour intervals ending01..next00, never row00 (which belongs partly to the previous date). Require explicit `precipitation_interval_start`/`precipitation_interval_end` matching that exact one-hour interval. `total_mm` is present only if all24 unique intervals and values are valid and the sum is finite; no partial sum presented as a day total. Use next-day00 solely as the end of the selected day's final interval, not as an instantaneous next-day observation. Last forecast day may legitimately have23/24 intervals and a null daily total.

Status for each metric: all24 known with a finite derived result→available; some known or aggregate overflow→partial; none→unavailable. An overflowed daily sum remains null even with24 known hourly values. Overall available only if all metrics available, unavailable only if all unavailable, otherwise partial. Mismatched date/invalid schema returns the same safe all-unknown structure, not a raised provider detail.

## UI

Place a compact weather block inside the existing selected-section inspector, not another sidebar/tab. Display precipitation total with known/24 completeness, native model soil-surface temperature range and snow-depth range (a clearly labelled conversion tocm is allowed). Mark any partial range; do not imply full-day extrema. Show selected UTC date and a short distinction from measured local ground/flood/frozen-layer state. Source provenance remains the existing ICON/Open-Meteo receipt in the section's disclosure. Existing air-temperature and moisture display may remain; no new HTTP request.

Mismatched date must hide old numbers. Missing values render asunknown, not0; a model0 must remain0. Out-of-horizon date remains the existing explicit gap. Do not compute passability, drying/recovery dates, bearing capacity or a frozen-ground verdict.

## Verification

TDD for complete/partial/missing inputs, accumulation boundary00/next00, duplicates, wrong dates/units, negative/non-finite/boolean input, zero/negative temperature preservation and overflow. Parent integration verifies derived summary from the same DTO with no extra provider calls. Fresh public API + desktop/mobile screenshots must show actual model values and match the received summary. Recheck existing profile and road/context flows; retain original requirements/design alignment and product incompleteness.
