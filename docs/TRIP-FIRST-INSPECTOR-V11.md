# V11 — trip-first section inspector

## Observed problem and product fit

Fresh wakeup15 checks: main branch, service active, public health200. Original well-access request and accepted map-first design re-read. In the current1688×1003 public control trip the selected-day weather starts at y917.78 and prior-day precipitation at y1194.78. The first inspector screen instead spends its space on repeated transect warnings and technical static metrics. Screenshot `qa/route-v2/wakeup15-before-desktop.png` records this actual baseline.

The original user asks about the trip date and vehicle mass after rain/thaw. Reorganize existing evidence around those questions, without adding an unvalidated mobility score or another provider. This is a presentation slice, not progress on the missing physical model.

## Scope

Only the off-road inspector (`analysis_kind=terrain_transect`) changes hierarchy:

1. Compact drawer title “Умови для поїздки”, length and explicit “Лінія аналізу, не шлях проїзду”. Remove repeated terrain-only header paragraphs; preserve original road header/source copy.
2. Existing section selectors and a visible point-sample/noncontinuous limitation.
3. Current server-plan vehicle kind/full mass (not a form preview) and selected date. Show mass without rounding away request precision. Invalid/missing vehicle metadata must remain unavailable, not a default20t truck.
4. Always-visible statements: “Проїзність не оцінено.” and current inundation/vehicle clearance unknown. They cannot be hidden in a disclosure or contradicted by a green status.
5. Existing selected-date weather card, including seven prior UTC days, moved before static terrain metrics. Use the same component and validated values, no second summary/parser or guessed wetness inference. An out-of-range weather date remains visible, with no substituted date.
6. Existing dated Sentinel-2 point card remains visible with its limitations.
7. Existing static ground composition, DSM, WorldCover tree fraction, historical canopy and their detailed limitations grouped inside collapsed native `details.terrain-details` (“Місцевість · ґрунт, рельєф, ліс”). Keep all existing values, units, years and no-normalization/QC semantics. Existing source/timestamp/digest disclosure remains available separately.

`SectionContext` accepts optional `analysisKind` and `vehicle:RouteRequest['vehicle']`. `RoutePlanner` supplies these from the accepted plan. Other callers retain the legacy layout by default; road rendering, endpoint payloads, requests, backend, caches, budgets and data availability do not change. At most one WeatherDayConditions instance per rendered context. Retain existing date/section/revision guards; parent invalidates the plan when date, A/B, vehicle or mass changes.

## Boundaries

- Weather/archived forecasts do not become observed rain, ground wetness or bearing capacity.
- DSM is not bare-earth slope; canopy/tree fractions do not become stem spacing or clearance.
- SCL/cloud/static-water classes do not establish current inundation.
- Transect is not a routed/approved corridor. No off-road alternatives or transport-dependent recommendation is invented.
- Critical unknowns remain visible while detailed data are collapsed.

## Acceptance

Use RED→GREEN component/integration tests for off-road DOM priority, actual vehicle precision, malformed parameters, collapsed terrain and retained source/soil/satellite values, disclosure without requests, out-of-range date and legacy road layout. Existing section/date/late-response clearing tests must continue passing. Verify actual live desktop/mobile screenshots: weather and prior precipitation move above the desktop fold from the recorded baseline, map remains dominant, mobile has one inspection sheet with usable native disclosures, no overflow or runtime errors. Verify plan-bound parameters and native current-point weather values agree with public API, section change and date/mass invalidation remove stale content, request count does not grow. Recheck public assets and health. No overall product completion claim.
