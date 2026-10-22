# Milestones

Status legend: ✅ done · ⏳ next · ⬜ not started

| # | Milestone | Owner | Status |
|---|-----------|-------|--------|
| M0 | Django Foundation | Claude | ✅ |
| M1 | Fuel Data Processing & Station Geolocation | Claude | ✅ |
| M2 | Routing API Integration | Claude | ✅ |
| M3 | Fuel Optimization Engine | Claude | ✅ |
| M4 | API Validation & Performance | Claude | ✅ |
| M5 | Professional SaaS Dashboard | Codex | ✅ |
| M6 | Interactive Map & API Integration | Codex | ✅ |
| M7 | Testing & Independent Code Review | Codex | ✅ |
| M8 | GitHub, Postman & Loom Submission | Rakesh | ⬜ |

## M0 — Django Foundation

- Django 6.1 + DRF project under `backend/`, four apps: `core`, `routing`, `fuel`, `optimization`.
- Environment-based settings with safe defaults; `.env.example`.
- SQLite configured and migrated.
- `GET /api/v1/health/` returning `{"status": "ok", "service": "routefuel-api"}`.
- Consistent JSON error envelope for API errors.
- pytest + pytest-django suite; Ruff lint and format.
- README, architecture notes, this plan.

**Acceptance (all verified):** Django starts · dependencies installed · DRF works · SQLite
migrations succeed · `/api/v1/health/` returns 200 · tests pass · system checks pass · Ruff passes
· README · architecture doc · environment config documented · git initialised · no secrets or
generated files committed.

## M1 — Fuel Data Processing & Station Geolocation

- Profiled the real CSV (findings in [architecture.md](architecture.md#source-csv--measured-profile)).
- `FuelStation` model with exact decimal prices, geolocation source/accuracy/uncertainty fields,
  indexes and integrity constraints.
- `import_fuel_prices`: validation with per-row reasons, duplicate merging, atomic bulk upsert,
  `--dry-run`, idempotent re-import.
- `geolocate_stations`: offline Census Gazetteer, city-level, cached; unresolved stations keep no
  coordinates.
- `apps/fuel/queries.py`: routable-station filter and indexed bounding-box query.

**Verified results (supplied CSV, fresh database):** 8,151 rows → 6,626 US stations; 0 rejected;
620 Canadian rows skipped; 905 duplicate rows merged; 6,228 city-level, 398 unresolved,
0 address-level. Re-import: 0 inserted, 0 updated, 6,626 unchanged. 137 tests pass; Ruff clean.

## M2 — Routing API Integration

- `POST /api/v1/routes/` accepting `"City, ST"` / `"City, State"` or `{latitude, longitude}`
  for `start` and `finish` (mixable).
- Offline resolution: M1 Census gazetteer for places (ambiguous names rejected with candidates);
  Natural Earth 1:10m state polygons for coordinates (true point-in-polygon, 50 states + DC).
- `RoutingProvider` protocol + `OsrmProvider`: one GET per uncached route
  (`overview=full&geometries=geojson`), identifying User-Agent, connect ≤ 5 s / read
  `ROUTING_TIMEOUT`, no retries, strict response validation, explicit error codes.
- Distance in miles (÷ 1609.344), duration in minutes, GeoJSON `LineString`, `meta` with
  `cached`, `routing_requests` and the OSRM/OSM attribution the usage policy requires.
- Database cache (`routefuel_cache`, created by migration), deterministic direction-aware key,
  7-day TTL, errors never cached, cache faults non-fatal.
- Pooled HTTP client and startup preload of reference data.

**Verified (2026-10-21):** 261 tests pass (137 from M0/M1 + 124 new), including all failure
modes, cache reuse and request counting with OSRM mocked; `manage.py check`, `makemigrations
--check`, `ruff check`, `ruff format --check` clean. Fresh-database smoke test: `migrate` creates
the cache table, `import_fuel_prices` reproduces the M1 numbers (6,626 / 6,228 / 398), and every
documented response was exercised over HTTP against a local OSRM stand-in. Local overhead with
the stand-in: 5.5 ms uncached / 2.2 ms cached (tiny geometry), 200 ms / 72 ms (50k-point
geometry); exactly one provider call per uncached route.

**Not yet verified:** a live OSRM call *from the Django client* — the build machine and the
linked computer both block the host. The public server itself was queried separately
(Dallas → Atlanta: 1,259,435.7 m = 782.58 mi; New York → Los Angeles: 2,794.21 mi), confirming the
request and response format. Run the README curl examples against `runserver` on an unrestricted
network to close this.

**Endpoint naming:** M2 ships `POST /api/v1/routes/`. M3/M4 decide whether fuel stops extend this
response or live on a separate `route-plan` endpoint.

## M3 — Fuel Optimization Engine

- Find candidate stations within a corridor of the route and project them to route mileage.
- Range-constrained minimum-cost purchasing (500 mi range, 10 MPG → 50 gal tank).
- Gallons and cost per stop; total fuel cost; total gallons.
- Explicit, documented assumptions on starting fuel and what "expenditure" includes.
- Unit tests with hand-calculated expected costs, including infeasible routes.

**Done when:** results match hand-worked examples and the algorithm is provably no worse than greedy-cheapest.

**Built:**

- `POST /api/v1/routes/optimize/` with optional `vehicle` (`range_miles`, `mpg`,
  `starting_fuel_gallons` default full, `starting_fuel_price_per_gallon` optional).
- `optimization/geometry.py`: haversine cumulative distance, mile markers scaled to the provider
  distance, thinned matching line, grid index, station offset and route mile.
- Corridor: one indexed query over padded ~200-mile route boxes; keep stations within
  5 mi + their location uncertainty; unresolved stations excluded.
- `optimization/optimizer.py`: "fill up, refund later" (classical fixed-route optimal rule),
  explicit infeasibility with the failing gap, and a replay check on every plan.
- Response: stops with price, gallons, cost, fuel on arrival/departure, route mile and
  approximate-location metadata; summary separating fuel consumed, starting fuel used,
  fuel purchased, purchase cost, remaining fuel, and (only with a supplied price) starting-fuel
  value and estimated total. Decimal money, rounded per stop, totals = sum of lines.
- M2 `/routes/` unchanged; shared route cache.

**Verified (2026-10-21):** 358 tests pass (261 before M3 + 97 new); the optimiser matches an
independent DP solver on 11,000 random instances; `check`, `makemigrations --check`, Ruff clean.
Benchmarks with the real station DB and stand-in routes: optimiser < 1 ms; full request
13–96 ms in-process (2.5k–42k route points), 66–203 ms over HTTP; exactly one provider call per
uncached route, none cached (details in [architecture.md](architecture.md#performance-measured-locally-2026-10-21)).

**Not yet verified:** a real OSRM route through Django (egress blocked in the build
environment), so real-route stop choices and live latency are unmeasured.

**For review:** starting-fuel convention (full tank, purchases reported separately), the 5-mile
corridor, and whether small cost-saving top-ups should be suppressed by a per-stop cost.

## M4 — API Validation & Performance

- Final request/response contract (M3 added `POST /api/v1/routes/optimize/` alongside `/routes/`).
- Response size: gzip and/or a simplified display geometry for long routes.
- Input validation with field-level errors.
- Query efficiency (indexed bounding-box prefilter), timing measurements, caching.

**Done when:** typical cross-country requests return quickly on a warm cache and validation errors are field-specific.

**Built:**

- Live-routing investigation and `manage.py verify_routing` (real provider, no mocks).
- `manage.py benchmark_api` (stage-by-stage and end-to-end, median/p95, request counts).
- Geometry stored and served as pre-encoded JSON (`RawJSONRenderer`); per-process reuse of the
  route line and station selection (invalidated by station-data version); single-pass
  geometry processing.
- Request coalescing for identical concurrent route requests (cache lock, works across
  processes sharing the database cache).
- `geometry_detail: "simplified"` (25 m Douglas–Peucker, display only).
- Fuel-cost clarity: `estimated_total_fuel_cost_status`, `cost_note`; whole-trip cost
  calculated when it can be, never implied otherwise.
- Optional practical-stop policy (`stop_policy.min_savings_per_stop`), separate from the
  minimum-cost default.
- JSON `500 internal_error`; CORS defaults for both local dev origins.
- `docs/api-contract.md`; Postman collection + environment + stdlib runner.

**Verified (2026-10-21):** 392 tests pass (358 before M4 + 34 new; one M3 test's expected
summary gained the two new fields); `check`, `makemigrations --check`, Ruff clean. Cached
coast-to-coast request 112 → 11 ms, uncached 158 → 105 ms (stand-in provider, in-process);
over HTTP 142 → 15 ms cached. Postman collection: 8/8 expected statuses against `runserver`
with a local stand-in OSRM, cold and cached.

**Not verified:** any live routing provider from Django — all are blocked by the build
environment's egress policy (proxy 403). Run `python manage.py verify_routing` on an
unrestricted machine before the Loom recording.
## M5 — Professional SaaS Dashboard (Codex)

Completed and preserved in local commit `13fac92`. Next.js, strict TypeScript, Tailwind,
responsive navy/teal dashboard, validated form, typed API client and reusable map/result panels.
All seven M5 tests, TypeScript, ESLint and production build pass.
See [M5 report](m5-frontend-report.md).

## M6 — Interactive Map & API Integration (Codex)

Implemented MapLibre route/source updates, A/B endpoints, ordered fuel markers, geographic
uncertainty areas, two-way marker/card selection, popups and route fitting. Runtime response
validation protects the map and summaries. Previous valid results survive failed requests;
zero-stop plans succeed. Added optional stop policy and remaining-fuel display.

**Live verification, 21 October 2026:** the historical M2–M4 OSRM connectivity block no longer
reproduces on this local machine. `manage.py verify_routing` passed after populating the empty
local station database with the existing CSV importer (6,626 stations, 6,228 geolocated).
No Django source or API contracts changed. Dallas–Atlanta: 778.8 mi, three stops, $78.19 purchases.
New York–Los Angeles: 2,810.37 mi, 17 stops, $698.65 purchases. Fresh provider calls and cache reuse
were both verified; browser routes and marker/card interaction were checked independently.

**Quality:** 35 passing frontend tests (seven preserved M5 tests plus 28 deterministic M6 tests);
strict TypeScript, ESLint and production build. Browser checks at 1440, 1280, 768 and 390 px.
See [M6 integration report](m6-integration-report.md) for evidence, limits and acceptance.
M6 preserved separately in local commit `49b4c19`.

## M7 — Testing & Independent Code Review

Completed locally on 22 October 2026. Backend: 416 tests, system/migration checks and Ruff pass.
Frontend: 36 tests, TypeScript, ESLint and production build pass. Live OSRM reproduced both
long routes plus Dallas–Austin; fresh calls and cached requests were counted independently.
Postman stdlib runner: 8/8 HTTP statuses against real Django/provider results (JavaScript
assertions require Postman/Newman). Browser checks cover real maps and mobile selection.
Fixed numeric overflow handling, invalid floating configuration and signed rounded policy
cost deltas; optimizer logic unchanged. Added 300 thousandth-gallon reference-DP cases.

See [M7 report](m7-final-qa-report.md) for evidence and known limits. This was a Codex audit
against an independently formulated reference solver; no separate Claude/human sign-off is
claimed. M8 remains unstarted; nothing pushed.

## M8 — GitHub, Postman & Loom Submission

Clean public repo, Postman collection, Loom walkthrough under five minutes.
