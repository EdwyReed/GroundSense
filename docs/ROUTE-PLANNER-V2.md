# GroundSense v2 — route-first implementation contract

## Product boundary

Accepted visual reference: `design/route-planner-v2/screens/01-routes.png`; supporting states in the same directory. Primary scenario: A → B, trip date, vehicle and mass → alternatives on the map → selected section. Original user requirements: `inputs/user-requirements-extract.md` (roads/forest tracks, automated soil context, date and vehicle, recovery forecast). A/B routing is the current user's explicit clarification. No legacy registry/job/manifest navigation on the primary screen.

This increment implements ordinary road geometry and a working route-first interface. It must not pretend that car-profile road routing assesses 20-tonne passage, soil bearing capacity, wetlands on the chosen date or future recovery. Initial real checks use public non-operational reference points in Norway, outside conflict areas. Operational military routing, threat avoidance and combat-area forest-corridor discovery are not implemented.

## Separation

- `apps/api/route_planner.py`: bounded fixed-provider road-routing/geocoding adapter and endpoint registration, independently testable with injected httpx transport. Constructor has no network side effect.
- `apps/web/src/RoutePlanner.vue`: trip state, form, alternatives and section drawer.
- `apps/web/src/components/RouteMap.vue`: actual MapLibre basemap, endpoint selection, route geometry and map selection. Native map interactions, no raster mock used as live map.
- `apps/web/src/lib/routeTypes.ts`: shared frontend DTOs.
- Existing weather/raster adapters remain available for a later route-corridor enrichment layer; no automatic expensive source calls on every pointer event. Unknown terrain remains unknown.
- Parent integrates endpoint registration in `main.py` and replaces the default web entrypoint only after tests/build. Existing APIs/data are not deleted in this slice.

## API

`POST /api/v1/route-plans`, existing browser session + Origin/CSRF, JSON:

```json
{"origin":{"longitude":10.7387,"latitude":59.9139,"label":"Oslo A"},"destination":{"longitude":10.7849,"latitude":59.9399,"label":"Oslo B"},"trip_date":"2026-10-26","vehicle":{"kind":"truck_6x6","gross_mass_t":20}}
```

Point labels optional. Vehicle kinds `car`, `truck_4x4`, `truck_6x6`. Coordinates finite and in WGS84 bounds; date valid ISO calendar date; mass finite and positive, no boolean/string coercion. Reject malformed inputs with Ukrainian 422 details. Bounded nearby trips, not unbounded global requests. No provider URL accepted from caller.

Response shape:

```json
{"request":{"origin":{"longitude":10.7387,"latitude":59.9139,"label":"Oslo A"},"destination":{"longitude":10.7849,"latitude":59.9399,"label":"Oslo B"},"trip_date":"2026-10-26","vehicle":{"kind":"truck_6x6","gross_mass_t":20}},"status":"ready","routes":[{"id":"route-1","name":"Основний","distance_m":5931.5,"geometry":{"type":"LineString","coordinates":[[10.7387,59.9139],[10.7849,59.9399]]},"conditions":{"status":"not_assessed","summary_uk":"Умови ґрунту не оцінено"},"surface":{"paved_m":null,"unpaved_m":null},"segments":[]}],"source":{"id":"osrm","profile":"car","retrieved_at":"2026-10-26T00:00:00Z"},"vehicle_assessment":"not_assessed","date_assessment":"not_assessed","synthetic":false,"warnings_uk":["Дорожня геометрія: автомобільний профіль, не перевірка проїзду вантажівки."]}
```

Example numbers/geometry above are schema illustration; use actual complete provider geometry at runtime. `status`: `ready`, `no_route`, `unavailable`; no_route/unavailable have `routes:[]` and explanation in warnings. At most three actual alternatives, not three invented ones. No straight-line fallback. Provider snapping bounded; disclose source/profile, never advertise shortest as safest or soil-aware.

Prototype integrity limits: request body ≤8 KiB, with handler-side streaming rejection before appending bytes beyond the limit, including chunked/non-JSON requests. Endpoint separation ≤300 km; reported route length and cumulative geodesic polyline length each ≤600 km. A coarse consistency gate rejects distance/geometry disagreement beyond 2× plus 2 km. These are deliberately loose provider-response sanity bounds, not scientific validation, a guarantee that geometry follows roads, or a vehicle-suitability model. Every polyline edge participates, not only the start/end points.

`GET /api/v1/places?q=Oslo` (session, same request budget): `{places:[{longitude,latitude,label}],source:{id:"photon"},status:"ready"}`. Fixed Photon endpoint, bounded response, search on explicit submit/Enter (not every keystroke). Coordinate-pair entry and clicking on map remain available if geocoding fails.

## Frontend states and acceptance

Empty trip → point selection → search → actual alternatives. Changing A/B, date, vehicle or mass immediately invalidates results and pending responses; late route/geocode responses cannot overwrite newer state. Disabled search has a short reason. Errors retain inputs. A selected route shows geometry/distance; soil/surface values remain absent with readable explanation when not assessed. Clicking a route opens an honest basic detail drawer, not fictional soil measurements. Mobile uses map + bottom sheet. Header/sidebar proportions, cobalt selection and restrained palette follow the new design. No old scientific/asset workflow returns to primary navigation.

This contract is a first implementation slice, not completion of the requested soil-aware, date-aware, vehicle-aware routing product. Those missing capabilities remain explicit in the iteration receipt.
