# V9 — responsive selected-section reads

## Why this slice

Original request: access to wells through fields/forest, selecting A/B, date and vehicle mass. The map-first design requires changing sections and trip inputs without losing the map/form. V8 adds valid dated evidence but leaves every selection waiting for serialized reads. Fresh wakeup13 public browser resource timing:17.221s for context. An isolated real adapter run took18.1783s: SoilGrids Q0.5 point fractions13.3442s, native SCL2.4485s, other operations shorter. This is measured evidence, not a promise of passability or of network speed.

## Contract

- Keep `/api/v1/route-context`, request shape, complete response binding and existing UI. No background job, endpoint, new required input, source, progressive/partial-response protocol or extra browser request.
- Keep basic DSM/WorldCover point reads in their existing order. On off-road only, overlap four independent auxiliary lanes: bounded terrain evidence (its existing serial soil/window reads), chosen-date weather, historical TCD point, optional dated SCL point. At most4 auxiliary workers per admitted context, no detached work or persistent/unbounded executor queue; join all submitted tasks before build returns. Road context retains its original reads and never calls off-road adapters.
- Preserve source ordering and extraction scopes, source-local unknown fallbacks, timestamp semantics, raw values and digest provenance. No shorter timeouts, fewer soil fractions, substitute values or weaker QC to make a timing look better.
- Reuse the expensive off-road terrain-evidence bundle for the exact server midpoint and same static adapter identity for at most300 monotonic seconds, max64 LRU entries. This contains only static public source evidence, never workspace/plan/route/assessment-date/weather/SCL data. Keep original retrieval timestamps and digests; mark sources `cached:true` on reuse. Return deep copies.
- Cache only bundles whose source records are all available/partial and all three soil fractions are finite and within0..100%; non-closing independent fractions remain partial and unnormalized. Do not retain unread/unavailable soil or failed windows as a successful reusable bundle. Cache misses may overlap within the existing request slots; do not add waiting queues or change budgets.
- Ownership/expiry/route validation, CSRF/Origin, body guards,2 context slots, per-workspace/global source budgets and existing per-context cache stay before all source access. Cached source evidence cannot be used to query a foreign plan or skip admission. Do not touch those gates.

## Acceptance

1. Deterministic barriers show all4 auxiliary lanes enter concurrently; per-request width stays4 and all work is joined, including failure cases. Existing road/source/guards tests pass.
2. Exact midpoint/adapter cache: copies do not alias, original timestamps/digests survive, date/vehicle changes reuse only static evidence; different point/adapter, TTL expiry and LRU eviction cause a real read. Unavailable evidence is retryable, not cached as zero.
3. Real before/after profiling records operation intervals and source results. Fresh adapter cache means a fresh adapter cache only: GDAL/OS/provider caches are uncontrolled. Report observations, no SLA or statistically established speedup.
4. Public complete context still matches the selected server point/date. Replay a real SCL pixel/digest and run existing public acceptance guards. Reanalyse with another trip date and confirm original static provenance plus newly bound forecast/SCL date.
5. Desktop/mobile screenshots: map remains primary, current section selected, actual source values and limitations visible, no overflow/runtime errors. Stale evidence still clears immediately during trip edits.

## Deliberately still absent

No current wetness/inundation inference, corridor clearance, off-road alternatives, allowed vehicle mass, travel recommendation or reopening forecast. First uncached SoilGrids read can still be slow; this slice overlaps independent reads and avoids repeating a complete static bundle unnecessarily.
