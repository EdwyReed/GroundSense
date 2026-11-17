# V6 — map-linked section inspection

## Why this slice

The original requirements request date/vehicle-aware conditions for dirt/forest access to wells. The accepted design keeps A/B, date/vehicle/mass and the map on one screen, with a clicked section opening its evidence. Off-road currently exposes the section inspector but its dashed map line cannot select a section. Fix that interaction using the existing server-bound three sections, without new providers, endpoint geometry, workflow or suitability claims.

## Ownership and binding

- `RoutePlanner` owns selected section index (0..2), optional preview index, the current plan/route-bound server sections, and the currently loaded point evidence. Reset sections/selection/preview on route/plan/date/mode/input invalidation. Closing the inspector hides map section controls and preview but preserves selected section for reopening the same trip.
- `SectionContext` accepts optional `selectedSectionIndex`; remains self-controlled for existing isolated uses. On successful bound response emit `sections: RouteSection[]` plus the existing `section` event. Emit `selectSection: number` when a tab is chosen and `previewSection: number|null` on hover/focus/leave/blur. A controlled index change loads exactly that section once. Hover/focus must never call the API. Clear the loaded sample immediately during a new request; retain current-trip section geometry for further map choices. Ignore stale replies before emitting any geometry/evidence. Load the supplied section when reopened.
- `RouteMap` accepts optional `sections: RouteSection[]`, `selectedSectionIndex: number`, `previewSectionIndex: number|null`. Emit `section: number` and `previewSection: number|null`. Use server geometries and exact server sample points; do not generate or infer other environmental coordinates. Only show active-trip section controls while inspecting and not choosing an A/B point.

## Map interaction

- Separate GeoJSON source `inspectable-sections`, with properties `index` and `route_id`, containing at most the three bound section LineStrings. An invisible wider hit layer `section-hit` allows click/tap selection. A preview line source/layer shows hover/focus separately from loaded-point evidence. Existing gray dashed transect remains dashed and is never a solid driveable road.
- Three small native MapLibre DOM marker buttons (1,2,3) at the exact server sample points expose keyboard selection and visible geographic anchors. Their labels name the section and call it a point sample; `data-map-section-index` supports precise QA. Preserve marker/focus identity while switching between sections. Pressed state is selection, not data completeness, risk, or approval. Remove controls/listeners on unmount or invalidation.
- Clicking a bare analysis line can reopen the current inspector; once section geometry is present, section-hit selects the actual clicked section without a duplicate whole-route action. Road selection, endpoint picks, responsive fit padding and the existing selected sample layer continue to work. Hover/focus/section changes must not refit or jump the map.
- While waiting for section data, highlight the chosen section as selection only; the previous loaded sample point must disappear. Hover/focus previews never replace or claim new loaded data. Clear previews when selecting or leaving inspection.

## UI scope

Keep existing Ukrainian map-first desktop layout and the single mobile inspector sheet. Add one short section-selection hint, no new screen, panel stack, green passability badge, terrain score, water/flood claim or manual soil parameters. Point evidence and the existing sparse height/WorldCover profile remain explicitly non-continuous. Weather and field/frozen-ground limitations remain intact.

## Verification

Use vertical RED→GREEN tests for map click/marker keyboard state, preview without requests/refits, externally controlled section selection, old response rejection and parent binding/invalidation/reopen. Run existing web suite/typecheck/build and public Python/environmental acceptance unchanged. Fresh public desktop/mobile checks must use actual native clicks on map controls and a segment hit, verify the resulting `/route-context` section index and rendered values, and record no extra profile/provider request for preview. Save before/after screenshots and a browser JSON receipt. This verifies map inspection, not a trafficability model.
