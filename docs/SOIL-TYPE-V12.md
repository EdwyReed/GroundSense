# V12 — reference soil type in the off-road inspector

## Purpose

Original requirement `inputs/user-requirements-extract.md:29-33`: user enters date and vehicle mass, other environmental inputs are automatic, including historical mapped soil type. Existing selected-section SoilGrids fractions do not provide a named soil unit. Add that reference context in the existing terrain/soil disclosure, preserving V11 trip-first hierarchy and map-first A/B/date/vehicle workflow. No new input, layer, endpoint, suitability model or source-stack fanout.

FAO describes HWSD2 as linked soil-mapping-unit raster and database, correlated to WRB2022, maintained at1km/30arc-second resolution.[1] These are mapped natural-soil associations, not field measurements or road-bearing observations.

Parent native probe (not a fixture): selected server point59.98500020992624,10.733331822658165 reads SMU10124, WRB4`PZal`, SHARE`70`. Matching official MDB D_WRB4 row is `145|Albic Podzols|PZal`. HWSD2_SMU_METADATA calls SHARE “Share in Soil Mapping Unit” and WRB2 “Dominant Soil Group”. Do NOT render70% as pixel confidence, local sampled-area fraction, probability or a homogeneous whole unit. Secondary server point59.99700021001084,10.74666515543908 maps to the same SMU, not a second independent field survey.

## Boundaries

- Static reference only. Do not use trip date/retrieval timestamp as a soil observation date. Display `WRB 2022` as nomenclature, NOT observation year.
- Full mass/transport affect no inferred soil suitability here. No drainage/wetness, cohesion, CBR, bearing capacity, admissible mass or recovery-time inference.
- Keep HWSD class/share separate from SoilGrids fractions/depth250m and do not normalize either. Do not map HWSD USDA code to SoilGrids composition.
- Preserve unresolved dataset-specific commercial reuse status; public access is not a commercial license determination.
- Keep critical mobility/current-water/clearance unknowns visible outside disclosures; put this secondary reference beside existing natural-soil data.

## Backend contract

New `apps/api/soil_type.py`, class `SoilTypeSource`. Constructor `SoilTypeSource(cache_dir:Path, *, adapter_lookup:Callable[[],Any], monotonic_clock=monotonic)`; `read_point(latitude,longitude)` returns `(soil_type, source)` like canopy adapter. Network-free construction and section read: only reuse already-cached HWSD2 archives through existing HWSDSources native primitives; NEVER initiate the global archive downloads from a section click. Missing/unverified assets/parser/legend become explicit unknown. Reuse legacy `_sample_raster`/`_attributes`/bounded `_run_mdb`, not full legacy multi-source reads. Existing legacy HWSD public-data path continues working.

Allowed auxiliary change to `hwsd_sources.py`: add native affine/pixel row+column metadata to `_sample_raster`; preserve old fields/semantics. Verify WGS84/CRS84 and actual north-up30arc-second pixels before exposing that resolution. Preserve masks/NoData/zero/invalid metadata, no clamping.

Check cached archive byte caps and SHA sidecars before use. Native MDB must correspond to the verified DB ZIP member (bounded streamed comparison/verification; do not trust same file size alone). Bind compact evidence digest to requested coordinates, native cell/map-unit, selected matched native row/legend, raster ZIP SHA, DB ZIP SHA and actual MDB SHA. Save compact evidence JSON locally under cache_dir, with no private path/URL leaking into DTO. Do not leak full MDB rows or unrelated metadata columns.

Select only a single matching HWSD2_SMU row for the raster map-unit ID. WRB4 code is literal and bounded. Resolve its human name with a fixed D_WRB4 lookup on CODE, strict literal-code validation before SQL (mdbtools lacks parameter binding), matched row/cardinality checks. Do not guess names from tags or prefix. Reject ambiguous/wrong-ID rows. Parse SHARE as native numeric text with finite0<value<=100 validation, preserving the original percentage without renormalization.

Bounded exact-coordinate/adapter-identity cache:300s TTL/64LRU, deep-copy isolation, original retrieval time/digests. Cache only complete available results; unavailable/partial retryable. No trip-date key: it is static context. Existing section request budget/body/CSRF/workspace/queue behavior remains.

`soil_type` DTO (all keys present):

- `status`: available|partial|unavailable.
- `basis`: `hwsd_v2_smu_dominant_soil`.
- `requested_point`: exact `{latitude,longitude}`.
- `map_unit_id`: integer|null.
- `wrb_code`, `wrb_name`: string|null.
- `share_percent`: number|null.
- `resolution_arc_seconds`:30|null.
- `temporal_scope`: `static_reference`.
- `classification_system`: `WRB 2022`.
- `spatial_scope`: `soil_mapping_unit`.

`source`: id=`hwsd-v2`, product=`Harmonized World Soil Database v2.0`, status/qc, retrieved_at, observed_at=null, content_sha256 of compact exact evidence, plus data containing the archive/MDB digests and commercial_reuse=`not_established`. Omit URLs, process output and private paths. Overall statusavailable requires valid matched map unit/code/name/share/native resolution; partial may retain map-unit without a named class. Failures never substitute a class.

Parent owns `route_context.py` integration: optional `soil_type_source` injection into RouteContext; production source adapter uses a lookup of current `app.state.extra_sources.get('hwsd')` (so fake/absent adapters remain offline). Sequentially combine canopy and soil in one existing auxiliary lane; never exceed4 request-local joined workers or2 admitted contexts. Append soil source with `extraction_scope=soil_mapping_unit` and soil_type field only for terrain_transect when source configured. Road path unchanged. No new endpoint/provider request in browser; normal analysis still has plan/profile/context.

## Frontend contract

New `ReferenceSoilType.vue` and types in `lib/soilTypeTypes.ts`. Props `soilType:SoilTypeData|null|undefined`, `selectedPoint:LngLat`. Parent integrates it once inside existing collapsed `.terrain-details` adjacent to natural soil; don't edit parent files in the frontend task.

Validate basis, static/spatial/nomenclature identity, requested point binding (exact server coordinates), integer positive map unit, native30arcsec metadata, bounded literal code/name, finite0<share<=100, available status. Malformed/stale/missing data displays unknown, no invented values. Partial map-unit may be labelled known while name remains unknown. No raw HTML. Keep names as native English plus literal WRB code; do not invent translations.

Suggested copy: “Довідковий тип ґрунту”, “Albic Podzols · WRB PZal”, “Домінантний тип у картографічній одиниці10124”, “70% одиниці, не ймовірність у цій точці”. Metadata `HWSD2.0 · WRB2022 ·30″ (≈1км) · статична карта`. Limitations: “Склад одиниці може бути неоднорідним. Не польова проба, не поточна вологість і не несуча здатність.” Do not give the nomenclature year an observed_at label. Commercial reuse status stays explicit in source/provenance or component note.

## Acceptance

TDD adapter/native fixtures for actual BIL point and matched MDB+legend, caps/no downloads, no data/invalid pixel/CRS/grid/SQL token/missing or mismatched/ambiguous rows, incomplete share/name unknown, digest change with row/cell/DB input, native archive/MDB integrity, cache TTL/LRU/identity/deep copies. Component tests for valid70%, unknown/malformed/stale point, year semantics and no mobility claim. Parent adds lane/integration/road/guard tests and full suites.

Publish only after real native preflight. Restart backend only if needed under existing deployment mandate; re-read health. Public context values/evidence must replay against the exact BIL/MDB/legend, source digest and same-point UI. Preserve plan/profile/context count, native map section changes and trip invalidation. Take fresh before/after desktop and390×844 screenshots, inspect expanded soil while keeping weather primary/collapsed by default, no overflow/errors. One consolidated independent review, corrective pass only for real findings. Entire product remains incomplete.

## Sources

[1] https://www.fao.org/land-water/resources/tools/databases/hwsd/en — FAO HWSD official product and changelog
    > "HWSD v2.0 uses FAO 1990 Revised Legend for all soil units, correlated with World Reference Base for Soil Resources (2022)."
    > "Resolution of 1 km (30 arc-second) maintained."
