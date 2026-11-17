# 11. Live research card: warm two-layer public weather balance

**Status:** `live-warm-water/1` is a research-only calculation. It is not a road-strength, trafficability, or vehicle-mobility model.

## Input and time convention

`assess_public_weather(weather)` reads only the supplied `weather` mapping. It makes no data requests. `research_series` starts with a UTC initial-state row and then contains hourly rows. For hourly accumulated `precipitation` and `et0_fao_evapotranspiration`, rows 01–06 fill the first contiguous bin `[00:00,06:00)`; row 00 is never added as forcing.

The calculation accepts at most 72 hours and requires at least 24 complete contiguous hours. With `assessment_date`, the initial state must be at that UTC midnight. A timestamp gap, duplicate, null, NaN, negative precipitation/ET0, or incomplete 6-hour bin is not interpolated or stitched. The run stops at its first missing hour when a valid complete horizon remains; otherwise it abstains. Negative hourly rain/ET0 is rejected before aggregation (cannot cancel with a positive neighbour). Aggregates, every transition and residual must remain finite and bounded; numerical failures cannot publish a successful trajectory. Zero is a provider-model zero, not a field measurement or missing value.

Warm-only screen: every row within the evaluated complete horizon must have `soil_temperature_0cm > 2 °C`, `snow_depth == 0`, and `snowfall == 0`. Rows beyond 72 hours are not part of the experiment. Air temperature cannot establish thaw. The screen also does not resolve residual frozen history, which remains an explicit limitation. Current provider snapshots may include elapsed hours of today; this is not an as-of historical forecast/backtest.

## State and assumptions

The hypothetical profile has two layers: L1 `0–0.10 m`, L2 `0.10–0.30 m`. Initial L1 moisture is the thickness-weighted 0–1 and 1–3 cm grid moisture; initial L2 uses 3–9 cm grid moisture. Mapping shallow grid supports onto the deeper hypothetical layers is an assumption, not an observation. Invalid initial grid moisture is rejected, never clipped.

Three named deterministic scenarios are used: `slow-drainage`, `central-hypothesis`, and `fast-drainage`. They are sensitivity hypotheses, not probabilities, quantiles, measured soil properties, SoilGrids fractions, road parameters, or calibrated parameters. Each payload exposes its full numeric parameter set with `parameter_status=research_hypothesis_not_measured_or_calibrated`.

Initial surface storage `H=0 mm` is also a hypothesis, not measured absence of puddles. Shared hypothetical volumetric porosities are 0.45/0.43, field capacities 0.30/0.28 and wilting bounds 0.10/0.12 m³/m³. Slow/central/fast infiltration capacities are 2/4/8 mm/h, interlayer capacities 0.5/2/5 mm/h and bottom capacities 0.2/1/3 mm/h. Surface capacities are 5/5/3 mm. ET demand shares are 0.10/0.55/0.35 for surface/L1/L2, with layer efficiency multipliers exposed as `et1`/`et2`. They are explicit choices for sensitivity, **not literature-validated point parameters**. Units of state/flows are mm, capacities `kin/k12/kb` mm/h, `hmax` mm, `dz_1_m/dz_2_m` m, `por/fc/wp` m³/m³, and ET multipliers dimensionless.

The 6-hour transition follows the card-10 ordering: surface ET; precipitation, infiltration and overflow runoff; L1→L2 drainage; bottom drainage; then water-limited layer ET. ET0 is FAO reference demand, not actual ET. Actual ET is bounded by available liquid water. States and fluxes are mm water equivalent; `theta_1` and `theta_2` are m³/m³. Per-step residual is:

```text
(H' + L1' + L2' - H - L1 - L2)
- (precipitation - actual ET - overflow runoff - bottom drainage)
```

Internal infiltration and interlayer transfers cancel from this external balance.

## Research condition and drying window

`condition` is a conservative research category only. It is `adverse` if any available scenario ends with surface storage or either layer above its stated field-capacity threshold; otherwise it is `less_adverse`. `severe` is reserved by the response contract but is not assigned by this card. No category says anything about mobility.

A scenario reaches `drying_confirmed_at` at the end of the first two consecutive 6-hour steps (12 hours) where surface storage is zero and both layers are at or below field capacity. This is a discrete model-state criterion, not continuous field evidence. `drying_window.kind=scenario_bounds` reports the earliest successful scenario time. `latest` is finite **only if every scenario confirms**; otherwise it is null and the UI explicitly states no upper bound was established. `not_reached` means none reached the criterion in the evaluated horizon; `censored_scenarios` counts all unconfirmed or unavailable scenarios. An early confirmation is first passage, not proof no later rain causes recurrence.

## Sources and literature context

Payload source references preserve source IDs and content digests supplied with weather. Parameter values remain hypotheses even though the model structure is informed by:

- FAO-56, *Crop evapotranspiration*, Chapter 2: https://www.fao.org/4/x0490e/x0490e06.htm
- USDA NRCS, *National Engineering Handbook, Part 630, Hydrology*: https://directives.sc.egov.usda.gov/viewerFS.aspx?hid=21422
- FHWA, *Geotechnical Engineering Circular No. 5*, Chapter 5: https://www.fhwa.dot.gov/engineering/geotech/pubs/05037/05b.cfm

These references do not validate the hypothetical profile or make the resulting state observed.
