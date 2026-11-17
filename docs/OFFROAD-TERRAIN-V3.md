# Off-road terrain first — scope change

User clarification: the primary target is land without roads: forests, fields, wetlands and other off-road terrain. Elevation, moisture, soil and, where defensible, forest structure must be considered. OSRM road alternatives are now a secondary mode, not a model of off-road travel.

## This runnable increment

- Default to `Місцевість без доріг`; retain `Дорожні маршрути` explicitly as a separate mode.
- A/B/date/vehicle/mass stay on the accepted map-dominant screen. Do not restore scientific registries or require soil parameters from the user.
- POST `/api/v1/terrain-plans` uses the existing validation/session/Origin/CSRF/body-size and workspace-owned 16-plan/15-minute store. No routing/geocoding provider is called to construct this analysis. Bound A/B distance to 20 km, reject identical endpoints and antimeridian crossing explicitly.
- Return `analysis_kind=terrain_transect`, `geometry_kind=analysis_transect`, one geometry named `Профіль місцевості`, source `user-transect`, profile `not_routed`. The line is a user-requested sampling transect, NOT a found, optimized or traversable route. Never use it as a fallback for failed road routing or label it an alternative route.
- Reuse server-bound section context, three approximate equal-chainage sections. Selectively fetch public environmental data at the section midpoint, not road-snapped endpoints. Represent native spatial support, dates, gaps and source identities.
- Add natural-soil composition if the public source can be read. Preserve native uncertainty/closure limits; lack of soil data remains unavailable, never inferred from land cover.
- Add bounded local DSM slope and land-cover neighbourhood metrics. DSM is surface elevation including trees/buildings, NOT bare-earth road grade. Fraction of tree-class pixels is neighbourhood forest cover, NOT canopy density, trunk density or vehicle clearance.
- Read canopy cover separately from the existing native Copernicus TCD2018 EEA identify service: one fixed endpoint, embedded WGS84 point CRS, 64 KiB streamed body cap, no redirects and an 8-second transport timeout. Preserve 0% independently from NoData/255. Return a separate `canopy_cover` reference-year/10 m cell; never relabel this historical observation as current forest structure or infer stems/clearance. Service failure is local to this evidence, not a failure of the whole context.
- Keep date-specific model moisture separate from road/soil bearing capacity. No vehicle admission, recovery date or automated off-road route search is implemented by this increment.
- Initial actual-source checks use public non-operational Norway locations, including forested land, not conflict-area routing or threat avoidance.

## Still needed for the full product

A georeferenced terrain cost model with uncertainty and physically defensible vehicle parameters, actual soil coverage, continuous route/corridor data rather than three representative points, bare-earth terrain where available, current water/snow/ice observations, forest structure/clearance evidence, alternatives over terrain, and independently validated trafficability/recovery. A blue line or a successful source read does not satisfy these requirements.

The route-planner-v2 design remains the composition target. Its road-only labels and fictional assessment values do not override this clarified off-road scope. Verify desktop/mobile screenshots of the actual implementation.

## Executable checks

`qa/run_offroad_acceptance.py` verifies the real public Norway transect, native soil fractions and unnormalized closure, DSM slope, WorldCover window support, separate native TCD canopy percentage/reference year, chosen-date weather, raw-source digests, cached readback, workspace isolation and unchanged asset registry. It fails if a required provider value is absent; there is no synthetic fallback. `qa/route-v2/offroad-public-proof.json` is the latest actual receipt, not a mocked fixture.

`qa/route-v2/tcd-native-probe.json` contains genuine zero-cover cells and an out-of-coverage NoData control. Browser receipts/screenshots check the same map-first desktop/mobile composition, section changes and invalidation of the old result when the date changes. Out-of-horizon weather remains absent, not replaced by another day.
