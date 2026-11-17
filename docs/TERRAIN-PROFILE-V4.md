# Terrain transect overview — bounded spaced samples

## Purpose and design

The primary use is forests, fields, wetlands and other terrain without roads. Three selected-section midpoints are useful detail but do not show the height and land-cover variation along A→B. Add a compact overview alongside the accepted map-first trip/result screen, not another registry or scientific workflow. Re-read `design/route-planner-v2/DESIGN.md`, `inputs/user-requirements-extract.md` and the later off-road clarification in `docs/OFFROAD-TERRAIN-V3.md` when accepting it.

## Contract

POST `/api/v1/terrain-profile` accepts only `{plan_id,route_id}`. Resolve the existing workspace-owned plan before any quota charge or provider I/O. Reject non-terrain plans explicitly. Keep Origin/CSRF/session, 8KiB streamed body, source budget and shared context-slot guards. Read providers in the threadpool. Cache at most16 responses for300 seconds, scoped to workspace/plan/route/date; do not cache a total outage. Constructors do no network work.

The server derives inclusive A→B chainage samples from its stored transect geometry: intervals≤250m, at most81 samples within the existing20km terrain bound. The browser cannot submit an alternate geometry, source URL or sample count. Include endpoints, distance, actual sample spacing and requested point coordinates.

Read only fixed approved Copernicus GLO-30 DSM and ESA WorldCover2021 URLs from the existing StaticSources templates. Group points by tile and open a tile once, with at most6 unique tile attempts per product. Use native CRS transformation, explicit raster bounds, masked1×1 samples, finite checks before/after native scaling and known WorldCover codes only. NoData/unknown stays null; real zero and negative DSM heights survive. Preserve actual raw-read evidence with existing bounded StaticSources provenance storage. Do not fetch SoilGrids, weather or TCD at every overview sample; those remain selected-section evidence.

Response:
- `plan_id`, `route_id`, `trip_date`, `status`, `synthetic:false`;
- `evidence_scope:spaced_point_samples`, `coverage:not_continuous`;
- `distance_m`, `sample_spacing_m`;
- `points:[{chainage_m,point:{longitude,latitude},elevation_m,land_cover_class,land_cover_label}]`;
- `sources`: separate DSM/WorldCover source records with `extraction_scope:transect_samples`, support/reference year, native CRS/sample scope, retrieval timestamp and evidence digest;
- `warnings_uk`: sparse samples can miss obstacles, DSM includes trees/buildings, static cover does not establish current inundation, no trafficability model.

A failed tile/product does not erase the other product or successful samples. No continuous-coverage percentage, passable distance, route score, ground-bearing capacity, total ascent, grade guarantee or vehicle recommendation is derived.

## UI acceptance

A compact height profile with sample-position land-cover markers belongs in the existing result sidebar. It must also be reachable in the mobile bottom sheet while inspecting a section. No extra column or new global navigation. Show A/B distances, native DSM units and known/total sample counts. Break the plotted line at missing heights; no filled/interpolated trace across gaps. The visible caveat must say these are samples, not continuous coverage; WorldCover is2021. Unknown cover is visually distinct from known non-forest and from a known bare-ground class.

Preserve trip invalidation and stale-response guards. Profile response plan/route/date binding must match its current props. Unmount/date/route edits discard old replies. An expired plan offers a new analysis; other faults permit retry without losing A/B/date/vehicle. Existing selected-section soil/moisture/canopy context remains available and independent.

Verify real Norway API and fresh desktop/mobile rendering, before/after screenshots, failures/gaps with deterministic fixtures, source/budget/workspace guards, and existing road-mode regression tests. The full original product remains unfinished until continuous evidence, defensible vehicle effects and current wetness/recovery are implemented and validated.
