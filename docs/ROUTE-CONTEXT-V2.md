# v2 selected-section environmental context — incremental contract

Primary screen remains the accepted route planner. This slice adds actual environmental data behind a selected road section, not a point registry, admission decision, or terrain-aware route ranking. Initial live checks remain public Norway reference points; no operational conflict-area routing/threat avoidance.

## Server binding

Ready `/route-plans` responses gain `plan_id`: opaque 32-hex handle. Retain server-produced trip/route geometry in a thread-safe bounded store (16 plans, 15-minute TTL, workspace ownership, deep-copy snapshots). `/route-context` never accepts client geometry or arbitrary source URLs.

`POST /api/v1/route-context`, same session+Origin/CSRF, body <=8KiB:

`{"plan_id":"32-hex handle","route_id":"route-1","section_index":0}`

Indices0..2 identify three approximately equal chainage sections. Server derives their geometry and representative midpoint from its stored provider polyline using cumulative geodesic length, not vertex index. Missing/foreign/expired plan:404, malformed input:422. Validate before budget/source I/O; use existing source budget and non-queuing shared context semaphore. No provider call in constructors. Never hold a global lock across network I/O.

Response DTO:

- `plan_id`, `route_id`, `section_index`, `trip_date`, `status` (`partial/available/unavailable`), `synthetic:false`.
- `sections`: three `{index,from_m,to_m,point:{longitude,latitude},geometry:{type:"LineString",coordinates:[...]}}` derived from actual geometry. Distances are approximate chainage, not separately surveyed road sections.
- `evidence_scope:"point_sample"`, `coverage:"not_continuous"`.
- `land_cover`, `terrain`, `sources`: native ESA WorldCover2021 and Copernicus DSM context from existing StaticSources primitives. Read ONLY land cover and terrain, not the full nine-request SoilGrids quantile stack on every click. Full static probe took ~50s; this latency is a demonstrated reason for a narrower read. Ground composition stays explicitly unknown in this slice.
- `weather`: existing validated LiveWeatherClient DTO filtered to selected UTC date, preserving native units, model grid coordinates, source hash/timestamp and QC. Exclude research_series from this response. If date is outside model horizon, return explicit `status:"date_out_of_range"`, no substituted date. Other provider failures stay source-local and sanitized, not raw exception URLs.
- `warnings_uk`: point samples do not describe continuous segment coverage; land cover2021 is not current inundation; weather-grid moisture is not road bearing capacity; vehicle/recovery not assessed.

Cache successful/partial context results boundedly for5min, keyed by workspace+plan+route+section+trip date, with immutable copies. At most two concurrent context requests, no background executor queue. Known provider I/O timeouts remain in force; a loading error must preserve route/inputs.

## Frontend

Selected-route drawer gains three section buttons, compact actual land-cover/DSM and date-specific weather values, sources disclosure and explicit gaps. Loading begins on opening details/choosing a section, not every map pointer move or automatically for all alternatives. Stale context replies cannot appear after route/trip/section changes. On mobile the inspector remains inside the existing bottom sheet. Do not color a whole section as dry/wet from one sample. Preserve the road geometry/vehicle assessment distinction.

This is partial original-product progress: selected-section context. Ground composition, continuous wetland detection, forecasting recovery, vehicle/road restrictions and validated trafficability remain outstanding.
