# Milestones

Status legend: ✅ done · ⏳ next · ⬜ not started

| # | Milestone | Owner | Status |
|---|-----------|-------|--------|
| M0 | Django Foundation | Claude | ✅ |
| M1 | Fuel Data Processing & Station Geolocation | Claude | ✅ |
| M2 | Routing API Integration | Claude | ⏳ |
| M3 | Fuel Optimization Engine | Claude | ⬜ |
| M4 | API Validation & Performance | Claude | ⬜ |
| M5 | Professional SaaS Dashboard | Codex | ⬜ |
| M6 | Interactive Map & API Integration | Codex | ⬜ |
| M7 | Testing & Independent Code Review | Claude + Codex | ⬜ |
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

- Resolve start/finish (US only) without per-request geocoding calls where possible.
- One OSRM `route` request per uncached trip; full GeoJSON geometry and distance.
- Timeouts, provider-error mapping to clean 4xx/5xx responses, response caching.
- Tests use mocked HTTP (no network in CI).

**Done when:** a route request makes at most one external call, and every failure mode returns a documented error.

## M3 — Fuel Optimization Engine

- Find candidate stations within a corridor of the route and project them to route mileage.
- Range-constrained minimum-cost purchasing (500 mi range, 10 MPG → 50 gal tank).
- Gallons and cost per stop; total fuel cost; total gallons.
- Explicit, documented assumptions on starting fuel and what "expenditure" includes.
- Unit tests with hand-calculated expected costs, including infeasible routes.

**Done when:** results match hand-worked examples and the algorithm is provably no worse than greedy-cheapest.

## M4 — API Validation & Performance

- Final request/response contract for `POST /api/v1/route-plan/` (name confirmed in M2).
- Input validation with field-level errors.
- Query efficiency (indexed bounding-box prefilter), timing measurements, caching.

**Done when:** typical cross-country requests return quickly on a warm cache and validation errors are field-specific.

## M5 — Professional SaaS Dashboard (Codex)

Next.js, TypeScript, Tailwind. Sidebar, trip inputs, results panels, loading and error states.
Light theme, navy/teal accents, no placeholder statistics.

## M6 — Interactive Map & API Integration (Codex)

MapLibre GL route line and fuel-stop markers wired to the live API.

## M7 — Testing & Independent Code Review

Coverage review, edge cases, a fresh-eyes code review, fixes.

## M8 — GitHub, Postman & Loom Submission

Clean public repo, Postman collection, Loom walkthrough under five minutes.
