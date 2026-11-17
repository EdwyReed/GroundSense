# V14 — inspect a chosen position on the terrain line

## Product decision

Original requirements (`inputs/user-requirements-extract.md:7-17,29,57`) ask for trip conditions for access to a well over fields/forest, with automatic environmental inputs. Accepted design (`design/route-planner-v2/DESIGN.md:19-24`) makes the map/selected-place inspector the workflow. Current three section-midpoint samples cannot inspect a small mapped feature between them. Enable a user-chosen position along the stored unsnapped A→B terrain line, not arbitrary coordinates, using the existing inspector and `/route-context`.

No routing/alternative search, vehicle suitability, continuous corridor, current flooding, drying prediction or new source is introduced. Norway is the live non-operational reference. Existing road mode stays unchanged.

## Wire contract

- Existing request `{plan_id, route_id, section_index}` and its response remain unchanged.
- Terrain-only request adds optional `sample_chainage_m`: a finite non-boolean numeric distance in metres from A, bounded 0..20000, inside the selected section's actual server-derived interval and full stored line length. Strings/null/bools/NaN/Inf/overflow/out-of-bounds reject with422 before source work/budget consumption. A road request with this field rejects422; legacy road requests remain unchanged.
- Resolve after workspace ownership/route lookup, before cache/admission/provider work. Derive coordinates solely from the complete validated stored geometry, using the existing cumulative geodesic-segment lengths and interpolation. No client latitude/longitude or URL is accepted for sampling. Bound geometry vertices to256 and total length to20km for the new path; reject invalid/non-finite coordinates or a global intermediate detour.
- New-path response adds `sample_selection: {kind: 'line_chainage', chainage_m: number, point: {longitude, latitude}}`. Legacy response omits it. `sections` remain the three server-derived sections/midpoints; `section_index` stays0..2. Every terrain/weather/canopy/SCL/soil read uses the resolved selected point.
- Cache identity includes optional chainage (None distinct from0); preserve workspace/plan/route/date isolation, TTL300s/LRU16 and existing exact-point static cache. Two positions in one section must not collide. Preserve two context admission slots/four joined source lanes, ownership, body/Origin/CSRF gates, source budgets, strict JSON and safe error handling. Pure validation errors become422, not500.

## Frontend

- Only off-road line clicks can request a new sampling position. Project onto the selected stored polyline and calculate chainage using the same earth radius/segment-length convention (6371000m). Map section buttons keep their current midpoint quick-selection behaviour; road clicks retain their current behaviour.
- Retain keyboard/touch operation without requiring a precise map click: a compact native disclosure in the existing inspector exposes an accessible position range and explicit submit button. Range input/hover is network-free; only committed selection issues one existing context request. Do not add environmental parameters to the trip form. Display distance from A and state this is one point, not corridor coverage or source accuracy.
- Preserve map-first380px desktop sidebar/single mobile sheet and trip-first weather hierarchy. No new screen, provider, profile fetch or map layer is needed; existing inspection point moves to the exact server-resolved point while section highlight stays the selected section.
- Clear the previous context/inspection point before loading; reject late replies by revision and exact selected binding. Atomically/batched selection changes must not issue duplicate requests for index+chainage changes.
- Validate new response kind/finite chainage/point against the request and stored route/section geometry before rendering any data. Validate SCL/HWSD against the actual sample point, not the section midpoint. A legacy or wrong-point reply must not masquerade as the requested line pick. Trip/date/mass edits remove the selection and all stale data.

## Acceptance

1. TDD: backend selection, endpoint422/403/404/body guards, no invalid-selection source/budget work, cache collision/zero, road isolation; frontend projection/binding, one-request map/keyboard commit, stale clearing and unchanged legacy quick sections.
2. Full suites/typecheck/build/audit; preserve known existing dependency/bundle warnings.
3. Native public reference: fresh plan/profile/context, select a real short mapped feature between the three midpoints where possible; replay the selected point against native WorldCover/DSM and source evidence. No synthetic fallback. Same plan/profile retained, one context request per new point.
4. Actual desktop/mobile screenshots and DOM measurements against the accepted design; keyboard control, old-response rejection, date/mass invalidation, no overflow, clean browser restoration. Public assets match build and service health passes.
5. One consolidated independent review; at most one bounded corrective batch/final review if a real issue appears. Full product remains incomplete.
