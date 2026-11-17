# V16 — dated satellite classes at existing A→B profile points

## Product decision

Continue the civilian well-access scenario in `inputs/user-requirements-extract.md` and the map-first flow in `design/route-planner-v2/DESIGN.md`. The existing inspector has one dated SCL pixel, while the existing profile has only DSM and static WorldCover. Add dated SCL at the **same discrete profile points**, with direct inspection through the existing V14 chainage flow. Do not introduce another planner, mandatory input, endpoint, synthetic dataset, or mobility model.

This is not continuous corridor coverage. Native preflight `qa/route-v2/wakeup21-scl-profile-preflight.json` independently read scene `S2C_32VNM_20261026_0_L2A` at a bounded Norwegian reference line. The same real scene contains classes 4 and 5 along that line. The dense feasibility probe is not a production trace or a statistical estimate of land-cover proportions.

## Publisher semantics

SCL is a scene classification, produced at 20 m and resampled to 60 m; actual raster metadata, not a product-name assumption, determines the displayed resolution.[1] Low clouds or fog can be omitted and classified as not vegetated, so class 5 is neither dry ground nor a guarantee of cloud-free surface.[2]

Water class 6 means a dated classified pixel, not present flooding or a ford. Vegetation does not establish dry/passable ground. Snow/ice does not establish frozen depth or bearing capacity. Cloud, shadow, NoData and gaps remain explicit. Satellite observations do not predict a future trip date.

## Backend contract / ownership

Backend owner may edit only `apps/api/surface_profile.py`, `apps/api/surface_observation.py` (a narrow reusable catalogue geometry primitive only), `apps/api/terrain_profile.py`, and corresponding new tests under `tests/runtime_routes/`. Preserve point-context V8 behaviour and road mode. TDD before production edits.

- Add `SurfaceProfile(cache_dir, *, transport=None, clock=None)` with `read_points(points, assessment_date) -> (summary, source)`. Each supplied point has `{chainage_m, point:{latitude,longitude}}`; accept 2..81 finite, strictly increasing chainages, first zero, last <=20 km, bounded WGS84 points, canonical YYYY-MM-DD. Validate before I/O.
- Reuse SurfaceObservation timestamp, allowed-asset, bounded STAC/provenance primitives where sensible. Exactly one bounded STAC search with the complete trusted point polyline in `intersects`, <=12 candidates, one latest valid scene among returned rows, no pagination or older-scene fallback. Same ten-day lookback and upper=min(selected-day end,retrieval instant) as V8.
- Exactly one approved SCL COG open; at most81 unique native1×1 reads. Transform each requested WGS84 point to native CRS. Outside extent, read failure, mask, declared asset/native NoData, NaN/Inf, fractional/out-of-range class, nonidentity categorical scaling → local null/unknown. Retain other readable points. Reject unsupported/rotated or nonsquare metadata rather than advertise a misleading scalar resolution. No clamping or resampling. Keep source units/scale/offset/native row/col/raw value in hashed finite evidence.
- Source failures must not erase existing DSM/WorldCover. Constructor no network. Bound cache <=16 entries, TTL300s, deepcopy and single-flight cold reads. Atomic evidence writes; no URLs/exceptions in public failures. Safe source descriptor id `sentinel-2-l2a`, extraction_scope `spaced_scene_classification_points`.
- Extend `/terrain-profile` response with `surface_observation_profile`, append the one source to existing `sources`. Existing `points`, WorldCover trace, status meaning and endpoint admission/body/ownership/CSRF/source budgets unchanged. No call from road paths. Use app data_dir for the source; isolated TerrainProfile tests without a source may emit an unavailable summary. One profile HTTP request remains one; endpoint cache avoids all source I/O.
- Keep work bounded inside existing admission. If overlapping independent profile reads, join the worker before releasing admission on every path. Do not introduce detached work or more than two request-local lanes. A serial bounded source read is acceptable; report native latency rather than fabricate an SLA.

Summary shape:
```
{
  status: available|partial|unavailable,
  basis: sentinel2_l2a_scl_profile_points,
  coverage: discrete_points,
  assessment_date: YYYY-MM-DD,
  retrieved_at: canonical UTC timestamp,
  observed_at: canonical UTC timestamp|null,
  scene_id: string|null,
  scene_age_days: integer|null,
  resolution_m: positive finite number|null,
  source_content_sha256: sha256-prefixed lowercase digest|null,
  selection_scope: bounded_catalogue_result,
  samples: [{chainage_m, requested_point:{latitude,longitude}, scl_class:0..11|null,
             condition:unknown|vegetation|not_vegetated|water|cloud|shadow|snow_ice,
             status:available|partial|unavailable}]
}
```
Class/status agreement follows V8: 4/5/6 available classification, 2/3 shadow,8/9/10 cloud,11 snow_ice partial,0/1/7 unknown partial, invalid/missing null unknown. Aggregate available only when all point statuses available, partial if some scene information exists, unavailable on complete source failure. Source data must bind exact samples/assessment/scene/native observations and expose a reproducible SHA256. `source.observed_at` equals summary timestamp. Missing scene has null observed/scene/resolution and unknown samples, never manufactured values.

Exact shared source-binding keys: `source.data.extraction_scope = spaced_scene_classification_points`, `source.data.assessment_date = summary.assessment_date`, `source.data.scene_id = summary.scene_id`, and `source.data.samples = summary.samples` (deep-equal content). Additional native/provenance fields are allowed. `summary.source_content_sha256` must equal the source descriptor's `content_sha256`, as a `sha256:`-prefixed64-lowercase-hex string when evidence exists; null on complete failure. Construct the evidence digest before adding its reference to the summary, avoiding a self-referential hash. Frontend validation must check these exact keys and digest equality rather than invent another naming convention.

## Frontend contract / ownership

Frontend owner may edit only `apps/web/src/lib/surfaceProfileTypes.ts`, new `SurfaceProfile.vue` and tests, `terrainProfileTypes.ts`, `TerrainProfile.vue`/its tests, `RoutePlanner.vue`/focused integration tests. Read existing components before editing. TDD; no deployment/dist writes.

- Optional typed summary consumed in existing profile; a compact closed native disclosure `Супутник уздовж A → B` below the existing static cover material. Summary shows scene date and sample count when valid; missing/invalid summary remains a closed unknown disclosure. Open/close causes zero requests.
- Expanded disclosure shows dated classes at existing chainages (up to81 rows, bounded scroll), actual resolution/age, no interpolated band or coverage percentage, plus plain limitations distinguishing discrete points from a corridor and observations from selected-date forecasts. Water is `Клас води`, never flooding/dryness; class5 `Без рослинності`, never dry/cloud-free. No red/amber/green passability coding.
- Validate strict canonical date/UTC timestamp grammar before parsing, observed<=retrieved and observed-day<=assessment, exact scene/source/digest/extraction binding, class-condition-status agreement, finite native resolution, sample count/order/coordinates/chainages equal to parent profile. Malformed payload must not hide the usable DSM/WorldCover profile. No self-authentication through an independent sample array.
- Wire an `inspect-point` event carrying a validated chainage through the existing `chooseChainage` parent function; no new endpoint. Buttons must work with mouse, Enter/Space, descriptive accessible labels. A committed point causes one existing context call, no new plan/profile; expanding/scrubbing causes none. Point inspection may happen for an unknown native class, but only with a valid source/profile/geometry binding.
- Add optional `routeGeometry` and `inspectionReady` props to TerrainProfile, passed from the saved selected route and available server sections in RoutePlanner. Require the complete saved LineString (distance and terminal chainage within0.01m), strictly increasing chainages starting at zero, and `pointAtChainage` coordinate agreement within1e-8degrees for every point before enabling inspect; missing/wrong geometry disables selection. A short prefix must not authenticate itself as the full saved line. Do not trust profile-returned geometry as authority. Existing V4 fixtures without geometry remain displayable without new selection buttons.
- Preserve date/vehicle/plan revision clearing and late-response rejection. Do not alter weather or its mobile fold position, road layout, map-first hierarchy, V14 map picker, or V15 display.

## Acceptance

1. Backend native local fixtures: projected CRS, zero/NoData, water/cloud/shadow/snow, outside extent, corrupt scaling/rotation, partial read failure, date/candidate/budget/asset bounds, exact digest changes, cache/single-flight/deepcopy, preserved V8 and profile/road guards.
2. Frontend tests: source/date/point/class mismatch fail closed locally, missing summary unknown, zero requests on disclosure, one existing V14 selection event, no selection from foreign/self-authenticated geometry, stale/date/vehicle clearing.
3. Native staged/public Norwegian read independently replayed against the exact named scene/native indices for every profile sample and evidence digest. No fabricated water class if the real line contains none.
4. Frequent desktop/mobile screenshots of real rendered data, closed and expanded. Same map-first layout, one drawer, no horizontal overflow; rain value remains inside390×844. Independent scoped review before public promotion. Full tests/typecheck/build/audit plus exact reviewed-file SHA verification.

## Integration verification notes

- Pass only the declared `{chainage_m,point}` input DTO to the real SCL adapter. Existing profile rows also contain DSM/WorldCover fields and are deliberately rejected by the adapter's strict validator. Exercise the real adapter through TerrainProfile with local native fixtures; a permissive adapter double did not catch this integration fault.
- Finite square native affine metadata is required; local fixtures cover missing native mask and declared native/asset NoData. Do not silently reclassify a declared NoData value.
- The isolated loopback API receipts `qa/route-v2/wakeup22-surface-profile-staged.json` and `wakeup22-surface-profile-horizon-staged.json` independently replayed every native pixel and the exact saved evidence digest for assessment dates2026-10-26 and2026-11-01. The reference line has11 samples and real classes4/5; do not manufacture water to demonstrate the UI.
- Browser tools reject private navigation, and the Desktop preview bridge did not answer. For pre-promotion component visual QA only, `qa/helpers/surface-profile-native-preview.js` mounts the unchanged SurfaceProfile with the successful, independently verified staged receipt. This is explicitly a captured-native component preview, not a live API test, new product data fallback, or transport/ownership proof. It performs no private browser requests and must never be deployed. Live public full-app acceptance remains required after a reviewed promotion.

## Non-goals

No continuous SCL trace/map overlay, extra scenes for missing pixels, current flooding, alternatives or route optimization, moisture classification, freeze-depth, vehicle admission, drying/recovery date, calibrated physics, automatic terrain recommendations, broad refactor, staging/commits/clean/reset. Full product remains in progress.

## Sources

[1] https://sentiwiki.copernicus.eu/web/s2-processing.md — SentiWiki S2 Processing
[2] https://sentiwiki.copernicus.eu/web/s2-products — SentiWiki S2 Products
