# V7 — native land-cover cells along the stored analysis line

## Why this slice

The original user needs automatic terrain context for off-road well access. Three section points and the <=250m spaced profile can miss a small water/wetland/forest patch. Read the WorldCover pixels intersected by the actual stored A→B polyline, rather than extending one sampled class across its neighbours. Keep the accepted map-first screen, form, inspector and mobile sheet. Compare against `design/route-planner-v2/DESIGN.md`, its actual route-screen PNG and `inputs/user-requirements-extract.md`.

This is a static raster centreline trace, not a searched driving route or a corridor-width assessment. WorldCover 2021 classes do not establish present flooding, soil bearing capacity, tree clearance, frozen depth or vehicle suitability. No routing/ranking, recovery prediction or threat-aware/conflict-area operation is introduced. Use the public Norway reference for live proof.

## Integration and wire contract

Extend the existing workspace-owned POST `/terrain-profile` response with `land_cover_trace`. Reuse its guarded plan/route/date, source quota, shared slots and cache; do not add another browser request or endpoint. Keep existing profile point fields and source records compatible. Replace the existing WorldCover read with one combined bounded reader, so there are still at most 6 WorldCover tile opens per profile, not 6 more. DSM reads remain unchanged.

`land_cover_trace`:

- `status`: `available` / `partial` / `unavailable` (read availability, not a condition rating).
- `evidence_scope`: literal `intersected_raster_cells`.
- `coverage`: literal `centerline_only`.
- `reference_year`: 2021; `resolution_m`: 10 (nominal publisher support, not a measured corridor width).
- `distance_m`, `known_m`, `unknown_m`: finite nonnegative metres; known + unknown = distance (within floating point tolerance).
- `cell_count`: number of positive-length native pixel spans inspected, <=8192; `tile_attempts` <=6.
- `segments`: ordered contiguous spans covering 0..distance, merged only when class is equal and endpoints meet. Every span has `start_m`, `end_m`, `class_code` (known WorldCover integer or null), `label` (canonical source label or null), and actual clipped LineString `geometry`. Unknown spans are explicit and must not be bridged. Geometry follows the stored polyline, never a snapped road. Zero-length corner contacts do not constitute a crossing.
- `sources`: normal bounded source provenance with native CRS/transform/scale/offset/NoData, exact extraction scope and content digest. Static year is not observed_at.
- `warnings_uk`: centreline-only / static year / no current inundation or transport admission.

Use trusted fixed WorldCover URLs via `StaticSources`, not payload URLs. Only the real WorldCover north-up EPSG:4326 grid is required; unsupported CRS/transform is explicit unknown, not a guessed reprojection. Split at 3-degree tile boundaries and then native cell boundaries. Preserve zero-length geometry vertices without infinite loops. Reject malformed/unbounded geometry before I/O. At most 8192 cell spans and 128 bounded native windows (32×32 pixels maximum) across the read; exhausted/missing/NoData/unknown/nonfinite/scaled-invalid cells remain null. No full raster, corridor bounding-box read or source-per-profile-point fan-out. Raw receipt JSON must be finite and safe; no arbitrary errors/URLs in user-facing failure text.

## Frontend

Add a compact static-cover summary alongside the existing height profile and a keyboard-operable map switch labelled `Покрив · 2021`. Different cover classes have a legend/text and colours; unknown is grey/dashed, never dry ground. Keep analysis-line geometry visually distinct from the cover overlay. A clear map note says `Лише лінія · не коридор` and warns that water/wetlands are 2021 classes, not current flooding. Only actual data appears; no fake wetness/slope toggles or fabricated values.

Use the same profile response via an emitted `trace` result: loading, error, invalidation and unmount emit null; late/stale/binding-mismatched or malformed traces are not mapped. RoutePlanner owns the current trace, clears it with trip/route invalidation, and passes it to RouteMap. Do not duplicate a fetch for the map. Missing optional trace remains compatible with old tests/responses. Validate ordered complete finite spans and native classes before display; reject mismatched total/bounds/coordinates rather than rendering foreign geometry. Switching the overlay must make no network call, alter no section selection and trigger no fitBounds. Clear map features when the trace is withdrawn. Keep desktop map dominant and a single mobile sheet; no new page or horizontal overflow.

## Evidence required

TDD vertical slices: narrow class between sparse profile points, diagonal/corner/zero-length traversal, tile boundary, native NoData/invalid class/scale/finiteness, bounded reads and cache/API guards. UI: one response supplies summary/map; toggle has no requests; stale/invalidated result clears source; unknown stays separate; road mode unaffected. Run relevant/full suites, typecheck and build, real public Norway profile/native readback, exact bundle match and actual desktop/mobile screenshots. Record unsupported/current-water/vehicle-model limits explicitly. No commits/reset/cleanup; preserve unrelated untracked work.
