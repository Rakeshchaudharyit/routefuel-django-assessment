# RouteFuel — architecture snapshot (22 October 2026)

A module-by-module description of the code as it exists on 22 October 2026: commit `8226559`
plus the uncommitted admin redesign and CSV/XLSX import. Design history and trade-offs are in
[architecture.md](architecture.md); field-level API details are in [api-contract.md](api-contract.md).

## Django project

| Path | Role |
|---|---|
| `backend/config/settings.py` | Environment-driven settings (root `.env` via python-dotenv); validates numeric settings at startup |
| `backend/config/urls.py` | `/` → redirect to `admin:index`; `/admin/`; `/api/v1/` (core + routing URLs, namespace `v1`) |
| `backend/config/wsgi.py`, `asgi.py` | Call `preload_reference_data()` so the gazetteer and state polygons load once per process |
| `backend/config/test_settings.py` | In-memory SQLite, LocMem cache, fixed test environment |

Installed apps: Django admin (through `apps.core.admin_apps.RouteFuelAdminConfig`), auth,
sessions, messages, humanize, contenttypes, staticfiles, `rest_framework`, `corsheaders`, and
the four project apps below. Middleware order: Security → CORS → Sessions → Common → CSRF →
Auth → Messages → Clickjacking.

## Applications

### `apps.core`

- `views.HealthView` — `GET /api/v1/health/` returns `{"status":"ok","service":"routefuel-api"}`
  without touching the database or the provider.
- `exceptions.api_exception_handler` / `ApiError` — every DRF error becomes
  `{"error": {"code", "message", "details"}}`. Unhandled exceptions are logged and returned as a
  generic `500 internal_error`.
- `renderers.RawJSONRenderer` / `RawJSON` — insert already-encoded route geometry into the
  response without re-encoding it.
- `admin_apps.RouteFuelAdminConfig`, `admin_site.RouteFuelAdminSite` — themed admin site whose
  index shows live station metrics (one aggregate query, permission-gated).

### `apps.routing`

| Module | Responsibility |
|---|---|
| `serializers.py` | `LocationField` (`"City, ST"` or `{latitude, longitude}`), `VehicleField` (range, MPG, starting fuel and its price; strict numbers, finite values, limits), `StopPolicyField`, `RouteRequestSerializer`, `OptimizeRequestSerializer` |
| `views.py` | `RouteView` (`POST /routes/`), `OptimizeRouteView` (`POST /routes/optimize/`); `_domain_errors()` maps domain exceptions to 422/502/503/504 |
| `locations.py` | `resolve_location()` — offline: Census gazetteer lookup for places (exact, compact, "City" suffix and consolidated-government aliases; ambiguity reported with candidates) and a US-polygon check for coordinates |
| `geography.py` | `UsBoundary` point-in-polygon over Natural Earth state polygons; `normalise_state()` |
| `providers.py` | `OsrmProvider` — one `httpx` GET per call, identifying User-Agent, timeouts; `RouteNotFound`, `RoutingTimeout`, `RoutingUnavailable`, `RoutingProviderError` |
| `services.py` | `plan_route()` — resolve both ends, reject identical points, check the database cache, coalesce identical concurrent misses with a short cache lock, call the provider once, cache successes for `ROUTE_CACHE_TTL` |
| `fuel_plans.py` | `plan_route_with_fuel()` — route → `RouteLine` → candidate stations → `optimize()` or `reduce_stops()` → `fuel_plan_payload()`; per-process memos for route lines, station selections and simplified geometry |
| `benchmarking.py`, `management/commands/benchmark_api.py` | Application-overhead benchmark (stand-in provider by default, `--live` optional) |
| `management/commands/verify_routing.py` | Live provider check: fresh route, cache reuse, fuel plan |
| `migrations/0001_route_cache_table.py` | Creates the `routefuel_cache` database-cache table |

**Route cache key:** SHA-256 of the provider name, base URL and profile, plus origin and
destination rounded to 5 decimal places (about 1 m; direction-sensitive). Errors are never cached. Cache read or write failures are logged, and
the request continues without the cache.

### `apps.optimization`

- `optimizer.py`
  - `Vehicle(range_miles, mpg, starting_fuel_gallons)`, where `tank_capacity_gallons = range / mpg`.
  - `Candidate(key, mile, price)`.
  - `optimize()` — minimum purchase cost on a fixed route, using fuel lots with refunds of dearer fuel.
  - `check_plan()` — replays a plan and enforces order, no dry tank, capacity and fuel balance.
  - `reduce_stops()` — opt-in greedy practical-stop policy.
  - `InfeasiblePlan` — reports the gap position.
- `geometry.py`
  - `RouteLine` — thins the route to vertices at least 0.5 mile apart and indexes segments on a
    0.25° grid. `locate()` returns a station's mile marker and its offset from the route.
  - `haversine_miles()`.
  - `simplify()` — Douglas–Peucker simplification for display geometry.

### `apps.fuel`

| Module | Responsibility |
|---|---|
| `models.FuelStation` | `opis_id` (unique), name, address, city, state, rack_id, `retail_price` / `max_retail_price` (Decimal 10,8), `price_observations`, latitude/longitude, `geolocation_source`, `geolocation_accuracy` (`unresolved` / `city` / `address`), `location_uncertainty_miles`, `created_at` / `updated_at`; indexes on (state, city), (latitude, longitude), retail_price; CHECK constraints for prices, coordinate ranges and geolocation consistency |
| `models.StationImport` | One admin upload: UUID, uploader, status (`previewed` / `applied` / `stale` / `expired`), file name/format/size/SHA-256, change-plan fingerprint, normalized rows (cleared once closed), summary, issues, result |
| `importer.py` | CLI pipeline: read → validate (`parse_row`, `parse_price`) → `merge_duplicates` (same location merges; different locations reject every row for that ID) → `upsert_stations` in one transaction |
| `geolocation.py` | `Gazetteer` (in-memory Census places), `geolocate_stations()` — town-level coordinates and an uncertainty radius from the place's land area; optional `opis_ids` scope |
| `queries.py` | `routable_stations()`, `stations_in_bounding_box()`, `BoundingBox.around()` |
| `station_import.py` | Admin import engine: `read_upload` (content-sniffed CSV/XLSX), `resolve_columns`, `validate_row`, `merge_rows`, `build_plan`, `create_preview`, `confirm_import`, `error_report_csv`, `xlsx_template` / `csv_template` |
| `admin.py`, `admin_import.py` | `FuelStationAdmin` (list, search, filters, field sets) with `StationImportAdminMixin` (import URLs and views) |
| `management/commands/import_fuel_prices.py`, `geolocate_stations.py` | CLI import and geolocation |
| `constants.py` | US and Canadian codes, price bounds (0.50–20.00), Decimal precision |
| `migrations/0001_initial.py`, `0002_stationimport.py` | Station table; import-preview table |

## Request flow: `POST /api/v1/routes/optimize/`

1. `OptimizeRequestSerializer` validates shape and ranges (400 on failure). Vehicle defaults:
   500 mi, 10 MPG, a full 50-gallon tank, no starting price.
2. `resolve_location()` resolves both ends offline (422 if unknown, ambiguous or outside the US).
3. `plan_route()`: cache hit → 0 provider calls; miss → one OSRM request (`overview=full`,
   GeoJSON geometry), then the result is cached.
4. `route_line()` builds or reuses the thinned `RouteLine`.
5. `select_stations()`: a station-data version check (routable count, latest `updated_at`, max
   uncertainty), then one indexed bounding-box query over ~200-mile route pieces. Each
   candidate is kept when its offset is within `FUEL_CORRIDOR_MILES` plus its uncertainty radius.
6. `optimize()` (or `reduce_stops()` when `stop_policy` is present), then `check_plan()`.
7. `fuel_plan_payload()` formats Decimals: gallons to 0.001, per-stop cost half-up to the cent,
   total = sum of stop costs. A whole-trip cost is computed only when the starting fuel's
   price is known or no starting fuel was used.
8. `route_plan_payload()` embeds the full or simplified geometry as `RawJSON`. `meta` carries
   provider, attribution, `cached`, `routing_requests` and `timings_ms`.

## Geolocation strategy

The CSV has no coordinates and most addresses are exit descriptions. Each station's city and
state are matched to a 2010 Census place, and the station receives that place's internal
point: `accuracy=city`, `source=census_gazetteer_places_2010`, with an uncertainty radius
equal to the radius of a circle with the place's land area (minimum 1 mile). Unmatched or
ambiguous towns stay `unresolved` with no coordinates and are excluded from routing. No
network geocoding is used. Current data: 6,228 `city` and 398 `unresolved`.

## Admin and authentication

- Native Django login, logout (POST only), database sessions (cookie `routefuel_admin_sessionid`,
  path `/admin/`, HttpOnly, SameSite=Lax, 8 hours, Secure unless `DJANGO_SECURE_COOKIES=false`),
  CSRF middleware, and password validators (minimum length 12).
- DRF views keep empty authentication classes and `AllowAny`, so admin sessions never
  authenticate the public API.
- Templates in `backend/templates/admin/`: login, a sidebar navigation, an operations index,
  and import screens under `fuel/fuelstation/`. Styles and scripts live in `backend/static/routefuel/`.

## Admin import workflow

`/admin/fuel/fuelstation/import/` → upload (POST, CSRF) → `create_preview()` writes a
`StationImport` only → redirect to `import/<uuid>/` → preview page →
`import/<uuid>/confirm/` (POST). That last step runs `confirm_import()`:

1. Atomically claim the preview (`previewed` → `applied`).
2. Rebuild the plan with row locks.
3. Compare its fingerprint with the preview's; if anything differs, nothing is written and the
   preview becomes `stale`.
4. Apply `bulk_create` / `bulk_update`.
5. Geolocate new and relocated stations, all in one transaction.

The `errors.csv`, `template.xlsx` and `template.csv` downloads are GET-only. Rules:
[admin-fuel-import.md](admin-fuel-import.md).

## Next.js frontend

| Path | Role |
|---|---|
| `src/app/page.tsx`, `layout.tsx` | Single-page dashboard; `api-documentation/page.tsx` shows the configured API base URL |
| `src/components/route-planner/dashboard.tsx` | Page state: health status, request lifecycle with `AbortController`, results and errors; loads the map with `next/dynamic` (no SSR) |
| `src/components/route-planner/route-form.tsx` | Start/finish, vehicle settings, starting price, optional practical-stop threshold; always requests `geometry_detail: "simplified"` |
| `src/components/map/route-map.tsx`, `route-layer.ts` | MapLibre map: GeoJSON route source and layers, start/finish and stop markers, uncertainty circles, popups, fit-to-bounds, provider attribution control |
| `src/components/trip-summary/`, `fuel-stops/` | Cost summary (purchases versus whole-trip cost) and selectable stop cards linked to map markers |
| `src/hooks/use-health.ts` | Health polling every 60 s with abort on unmount |
| `src/lib/api/client.ts` | `request()` with timeouts, an error envelope parser and network-error mapping; `getHealth`, `optimizeRoute`, `getRoute`; base URL from `NEXT_PUBLIC_API_BASE_URL` (default `http://127.0.0.1:8000`) |
| `src/lib/api/validation.ts` | Runtime validation of optimize and route responses before rendering |
| `src/types/api.ts` | TypeScript types mirroring the API contract |
| `tests/` | `api-client.test.mjs` (node --test), `validation.test.ts`, `integration.test.tsx` (Vitest + Testing Library) |

The dashboard does no optimization itself; all numbers come from the API.

## Error handling summary

| Layer | Behavior |
|---|---|
| Validation | 400 `invalid` with field details; DRF `parse_error` (400) and `unsupported_media_type` (415) |
| Domain | 422 `location_not_found`, `ambiguous_location`, `location_outside_us`, `same_location`, `route_not_found`, `no_feasible_fuel_plan` |
| Provider | 502 `routing_provider_error`, 503 `routing_unavailable`, 504 `routing_timeout` |
| Unexpected | 500 `internal_error` (logged, no internals) |
| Frontend | Client timeout, network/CORS failure, API errors and invalid responses each map to a user message; the previous valid plan stays visible |

## Performance measures in the code

- Reference data is loaded once per process; location resolution makes no I/O per request.
- One provider call per uncached route, a database cache, and request coalescing.
- Route geometry is cached and emitted as pre-encoded JSON; simplified display geometry is
  memoized.
- Station search: one indexed bounding-box query, then grid-indexed point-to-line matching on
  a thinned line.
- Per-process selection memo keyed by the station-data version, so edits and imports are seen
  on the next request.
- Optimizer: sort plus a lot queue (O(n²) worst case, under 3 ms on the longest real route).

## Automated tests (511 backend)

| File | Tests | Area |
|---|---:|---|
| `test_routing_api.py` | 90 | Routing endpoint, provider errors, caching, coalescing |
| `test_station_import.py` | 71 | Admin CSV/XLSX import |
| `test_optimizer.py` | 55 | Optimizer vs reference DP (`reference_optimizer.py`), invariants |
| `test_fuel_import.py` | 53 | CLI importer |
| `test_fuel_geolocation.py` | 45 | Gazetteer and geolocation |
| `test_api_integration.py` | 34 | End-to-end payloads and the response schema |
| `test_routing_locations.py` | 34 | Location resolution |
| `test_optimize_api.py` | 32 | Optimize endpoint and vehicle validation |
| `test_admin.py` | 24 | Admin authentication, permissions, CSRF, cookies |
| `test_m7_regressions.py`, `test_m7_optimizer_audit.py` | 17 + 7 | M7 audit regressions |
| `test_config.py`, `test_fuel_queries.py`, `test_route_geometry.py`, `test_health.py`, `test_urls.py` | 16 + 12 + 10 + 6 + 5 | Settings, queries, geometry, health, URLs |

Network access is blocked in tests (`conftest.block_network`). Frontend: 7 Node tests plus 29
Vitest tests (M8 count).
