# RouteFuel

A Django REST API that plans a driving route between two US locations and recommends where to
buy fuel so the trip costs as little as possible. Built as the backend assessment for the
Backend Django Engineer role at Spotter AI.

> **Status:** M0–M7 implemented and audited locally. Live OSRM routes were verified through
> Django and the dashboard on 22 October 2026. M8 has not started; nothing has been pushed.
> See the [M7 QA report](docs/m7-final-qa-report.md) for tests, measurements and limitations.
>
> **Station markers are town-level approximations, not verified pump locations.** Road access,
> detours and truck restrictions are unverified. Prices are a static dataset. The fuel model has
> no reserve and may arrive empty; confirm actual stops and fuel margins before travel.
>
> [API contract](docs/api-contract.md) · [Postman](docs/postman/) · [Milestones](docs/milestones.md)

## Assessment requirements

The API and dashboard:

1. Accept start and finish locations within the USA.
2. Calculate a driving route between them.
3. Return route geometry suitable for a map.
4. Identify cost-effective fuel stops along the route.
5. Use the employer-provided fuel-price CSV.
6. Assume a maximum range of 500 miles.
7. Assume 10 miles per gallon.
8. Report the estimated total fuel expenditure.
9. Support multiple fuel stops on long trips.
10. Minimise external routing API calls.
11. Respond quickly.
12. Handle errors gracefully.

## Technology stack

| Layer | Choice |
|-------|--------|
| Language | Python 3.12+ (developed on 3.13) |
| Framework | Django 6.1, Django REST Framework 3.18 |
| Database | SQLite |
| HTTP client | httpx (routing provider, from M2) |
| Routing | OSRM (from M2) |
| Tests | pytest, pytest-django |
| Lint / format | Ruff |
| Frontend (M5+) | Next.js, React, TypeScript, Tailwind CSS, MapLibre GL JS |

## Local installation

```bash
git clone <repo-url> routefuel
cd routefuel
cp .env.example .env            # then edit DJANGO_SECRET_KEY

python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
cd backend
pip install -r requirements-dev.txt
python manage.py migrate                 # also creates the route cache table
python manage.py import_fuel_prices      # load the CSV + offline geolocation (~2 s)
```

## Environment configuration

Settings are read from environment variables, or from `.env` at the repository root.
Real environment variables take precedence over `.env`.

| Variable | Default | Purpose |
|----------|---------|---------|
| `DJANGO_SECRET_KEY` | none — required when debug is off | Django cryptographic signing |
| `DJANGO_DEBUG` | `false` | Debug mode; enables the browsable API |
| `DJANGO_ALLOWED_HOSTS` | `localhost,127.0.0.1` | Comma-separated hosts |
| `DJANGO_CORS_ALLOWED_ORIGINS` | `http://localhost:3000,http://127.0.0.1:3000` | Comma-separated browser origins allowed to call `/api/*` (the Next.js dev server) |
| `ROUTING_BASE_URL` | `https://router.project-osrm.org` | OSRM-compatible routing server |
| `ROUTING_TIMEOUT` | `10` | Routing request timeout in seconds (must be > 0; connect capped at 5) |
| `ROUTING_USER_AGENT` | `RouteFuel/0.2 (Spotter AI assessment; …)` | User-Agent sent to the routing server (required by the OSRM usage policy) |
| `ROUTE_CACHE_TTL` | `604800` (7 days) | Seconds a successful route stays cached (must be > 0) |
| `FUEL_CORRIDOR_MILES` | `5` | A station is a candidate if its point is within this distance of the route **plus** its own location uncertainty (must be > 0) |

Non-finite floating-point settings are rejected. Invalid values (e.g. `DJANGO_DEBUG=maybe`, `ROUTING_TIMEOUT=0`, `ROUTE_CACHE_TTL=-1`) fail fast at startup with a clear message.

## Running Django

```bash
cd backend
python manage.py check
python manage.py runserver
curl http://127.0.0.1:8000/api/v1/health/
# {"status":"ok","service":"routefuel-api"}
```

## Running tests and quality checks

```bash
cd backend
pytest                   # test suite (uses in-memory SQLite and fixed test settings)
pytest tests/test_routing_api.py tests/test_routing_locations.py   # routing only
ruff check .             # lint
ruff format --check .    # formatting
```

The suite never touches the network: sockets are blocked in `tests/conftest.py`, and OSRM is
replaced with `httpx.MockTransport`. Passing tests therefore say nothing about whether the live
routing server is reachable — use the live check below.

## Live routing check

```bash
cd backend
python manage.py verify_routing                       # Dallas, TX -> Atlanta, GA
python manage.py verify_routing --start "Chicago, IL" --finish "Denver, CO"
```

Nothing is mocked. It prints the provider configuration and DNS result, makes one direct
provider call through the Django client, then calls `POST /api/v1/routes/` (uncached, then
cached) and `POST /api/v1/routes/optimize/`, and marks each check PASS/FAIL (exit status 1 on
failure). It makes at most two provider requests, 1.1 s apart. Expected Dallas → Atlanta
distance: ~778.8 mi (what the public OSRM server returned for these points on 2026-10-21).

The historical M2–M4 network block no longer reproduces locally. M7 independently reproduced
Dallas–Atlanta (778.8 mi, three stops, $78.19 purchases) and New York–Los Angeles
(2,810.37 mi, 17 stops, $698.65). Results depend on provider data and the imported CSV.

## Benchmarks

```bash
python manage.py benchmark_api                    # stand-in provider, 3 routes, 20 runs each
python manage.py benchmark_api --runs 50 --route newyork-losangeles
python manage.py benchmark_api --live --runs 5    # real configured provider (network)
```

Requests go through Django's test client (middleware, view, serialiser, renderer). The
stand-in provider answers in-process with synthetic geometry (straight segments through towns
along an interstate, 12k–51k points) — it measures RouteFuel's own work, not routing latency.
Only the benchmark's own cache entries are deleted. Results and before/after numbers:
[docs/architecture.md](docs/architecture.md#api-performance-m4).

## Postman

Import `docs/postman/RouteFuel.postman_collection.json` and
`docs/postman/RouteFuel.local.postman_environment.json`; set `base_url` (default
`http://127.0.0.1:8000`). Eight requests: health, Dallas–Atlanta route, Dallas–Atlanta optimised,
New York–Los Angeles optimised (simplified geometry), custom vehicle with starting-fuel price and
stop policy, invalid input (400), unreachable route (LA → Honolulu, 422 `route_not_found`) and
infeasible fuel plan (10-mile range, 422 `no_feasible_fuel_plan`). Each has Postman tests.

Without Postman: `python docs/postman/run_collection.py --base-url http://127.0.0.1:8000`
sends the same requests and checks status codes.

## Fuel data

```bash
python manage.py import_fuel_prices                 # import + geolocate new stations
python manage.py import_fuel_prices --dry-run       # validate and report only; writes nothing
python manage.py import_fuel_prices --file other.csv --show-issues 20
python manage.py geolocate_stations [--force]       # re-run offline geolocation only
```

The import is idempotent: running it again inserts and updates nothing unless the CSV changed.
Each run reports rows read, valid, rejected and skipped (with reasons), duplicates merged, and
stations inserted, updated, unchanged and present in the database but missing from the file.

**Results on the supplied CSV** (measured on a fresh database):

| | |
|---|---|
| CSV rows | 8,151 |
| Rejected (invalid data) | 0 |
| Skipped — Canadian stations, out of scope | 620 rows (112 stations) |
| Duplicate rows merged | 905 |
| US stations imported | 6,626 |
| City-level approximate coordinates | 6,228 (94.0%) |
| Unresolved (no coordinates) | 398 — 371 city not in gazetteer, 27 ambiguous |
| Address-level (verified) coordinates | 0 |
| First import + geolocation | 0.72 s + 1.22 s |
| Re-import + geolocation | 0.26 s + 0.31 s |

**Coordinates are approximate.** The CSV has no coordinates and almost no street addresses, so
stations are placed at their town's Census point and flagged `geolocation_accuracy="city"` with a
`location_uncertainty_miles` radius. Unresolved stations have no coordinates and are excluded
from route candidates. Details: [docs/architecture.md](docs/architecture.md#fuel-data-layer-m1).

## API

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/health/` | Liveness check. No database or external calls. |
| POST | `/api/v1/routes/` | Driving route between two US locations (M2). |
| POST | `/api/v1/routes/optimize/` | Route plus minimum-cost fuel stops (M3). |

Errors use one envelope: `{"error": {"code": "...", "message": "...", "details": ...}}`.

### `POST /api/v1/routes/`

`start` and `finish` each accept either form (they can be mixed):

```jsonc
{"start": "Dallas, TX", "finish": "Atlanta, Georgia"}                  // "City, ST" or "City, State"
{"start": {"latitude": 32.7767, "longitude": -96.7970},
 "finish": {"latitude": 33.7490, "longitude": -84.3880}}               // WGS84 decimal degrees
```

```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/routes/ \
  -H "Content-Type: application/json" \
  -d '{"start": "Dallas, TX", "finish": "Atlanta, GA"}'

curl -s -X POST http://127.0.0.1:8000/api/v1/routes/ \
  -H "Content-Type: application/json" \
  -d '{"start": {"latitude": 32.7767, "longitude": -96.797}, "finish": {"latitude": 33.749, "longitude": -84.388}}'
```

Response (`200`), illustrative historical values; geometry is abbreviated. Current M7 live
Dallas–Atlanta distance is 778.8 miles; provider results can change:

```json
{
  "origin":      {"label": "Dallas, TX", "latitude": 32.794176, "longitude": -96.765503, "state": "TX", "source": "census_place"},
  "destination": {"label": "Atlanta, GA", "latitude": 33.762909, "longitude": -84.422675, "state": "GA", "source": "census_place"},
  "route": {
    "distance_miles": 782.58,
    "duration_minutes": 848.4,
    "geometry": {"type": "LineString", "coordinates": [[-96.765503, 32.794176], "…", [-84.422675, 33.762909]]}
  },
  "meta": {
    "provider": "osrm",
    "attribution": "Routing © OSRM; map data © OpenStreetMap contributors (ODbL)",
    "cached": false,
    "routing_requests": 1
  }
}
```

* `geometry` is a GeoJSON `LineString` (`[longitude, latitude]` pairs, full resolution) — pass it
  straight to MapLibre/Leaflet. `distance_miles` = provider metres ÷ 1609.344, rounded to 0.01.
* City inputs resolve to the Census *internal point* of the place, so a city's coordinates are
  near its centre, not at a specific address. Coordinate inputs are used as given.
* `meta.routing_requests` is the number of external routing calls this response needed: `1` on a
  cache miss, `0` on a hit. Location resolution never calls the network.

**Errors**

| Status | `code` | When |
|--------|--------|------|
| 400 | `invalid` | Missing `start`/`finish`, wrong type, blank, not `"City, ST"`, latitude/longitude out of range or not a number (`details` is per field) |
| 400 | `parse_error` | Body is not valid JSON |
| 415 | `unsupported_media_type` | Body is not `application/json` |
| 405 | `method_not_allowed` | Anything other than `POST` |
| 422 | `location_not_found` | Unknown US state, or no Census place with that name in the state |
| 422 | `ambiguous_location` | Several Census places in that state share the name; `details.candidates` lists them — send coordinates instead |
| 422 | `location_outside_us` | Coordinates outside the 50 states + DC, or a Canadian province / US territory |
| 422 | `same_location` | Start and finish resolve to the same point |
| 422 | `route_not_found` | The provider found no drivable route (e.g. Hawaii ↔ mainland) |
| 502 | `routing_provider_error` | The provider rejected the request or sent an invalid response |
| 503 | `routing_unavailable` | Provider unreachable, rate limiting (429) or failing (5xx) |
| 504 | `routing_timeout` | No provider response within `ROUTING_TIMEOUT` |

For 422 location errors, `details.field` says which input failed (`start` is checked first).

```json
{"error": {"code": "ambiguous_location",
           "message": "'Cottonwood, AZ' matches 2 Census places. Send coordinates instead.",
           "details": {"field": "finish", "city": "Cottonwood", "state": "AZ",
                       "candidates": [{"name": "Cottonwood CDP", "latitude": 36.072383, "longitude": -109.890236},
                                      {"name": "Cottonwood city", "latitude": 34.719747, "longitude": -112.001252}]}}}
```

### Routing provider, calls and caching

* **Provider:** OSRM HTTP API (`/route/v1/driving/…?overview=full&geometries=geojson`), default
  the public demo server. Its [usage policy](https://map.project-osrm.org/about.html) allows at
  most one request per second, forbids heavy use and requires an identifying User-Agent and
  attribution (returned in `meta.attribution`). Use your own OSRM for anything beyond a demo:
  set `ROUTING_BASE_URL`.
* **Calls:** one HTTP request per uncached route, no retries, no per-station calls. Location
  resolution is offline. So a request costs exactly one external network call on a cache miss
  and none on a hit. Identical requests arriving together are coalesced: the first takes a
  short lock in the cache and calls the provider; the others wait for its result (works across
  processes sharing the database cache).
* **Cache:** successful routes are stored in Django's database cache (table `routefuel_cache`
  in the same SQLite file, created by `migrate`) for `ROUTE_CACHE_TTL` seconds. The key is the
  provider + server + coordinates rounded to 5 decimals (~1 m), direction-sensitive, so
  `"Dallas, TX"`, `"dallas, texas"` and the same coordinates share one entry. Errors are never
  cached. If the cache table is unavailable the request still succeeds, just uncached.
  Geometry is stored as JSON text and written into responses without re-encoding.
* **`geometry_detail`** (optional, both endpoints): `"full"` (default) or `"simplified"` — a
  Douglas–Peucker line within 25 m of the full route, for drawing only. Distances and fuel-stop
  mile markers always use the full geometry. The response says which one it returned
  (`route.geometry_detail`, `route.geometry_tolerance_meters`).

### `POST /api/v1/routes/optimize/`

Same `start`/`finish` as `/routes/`, plus an optional `vehicle` (all fields optional):

| Field | Default | Meaning |
|-------|---------|---------|
| `range_miles` | `500` | Distance on a full tank |
| `mpg` | `10` | Miles per gallon. Tank capacity = `range_miles / mpg` (50 gal) |
| `starting_fuel_gallons` | full tank (50) | Fuel on board at the origin, already paid for |
| `starting_fuel_price_per_gallon` | none | Optional. Only used to value the starting fuel; never invented |

Optional `stop_policy: {"min_savings_per_stop": "2.00"}` drops stops that save less than that
amount (re-optimising after each removal) and reports the extra cost against the minimum-cost
plan in `fuel_plan.stop_policy`. The default minimises continuous purchase cost before display
rounding, not stop count or rounded-cent totals. The policy is greedy: it can stop above the
minimum feasible number of stops. On the live New York–Los Angeles route, a $2 threshold
returns 11 stops for $700.74 (+$2.09); five stops suffice in the approximate candidate model.
Rounded `extra_cost` can be negative by a cent for effectively equal exact costs.

```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/routes/optimize/ \
  -H "Content-Type: application/json" \
  -d '{"start": "Dallas, TX", "finish": "Atlanta, GA",
       "vehicle": {"range_miles": 500, "mpg": 10, "starting_fuel_gallons": 50,
                   "starting_fuel_price_per_gallon": "3.199"}}'
```

Response (`200`), abridged. **This example was produced locally with the real station database
but a stand-in route** (straight segments through the Census points of I-20 towns, with the
778.8-mile distance the public OSRM server reported for this pair) because OSRM was unreachable
from the build machine. A real OSRM route will give different mile markers and may choose
different stations:

```json
{
  "origin": {"label": "Dallas, TX", "...": "..."},
  "destination": {"label": "Atlanta, GA", "...": "..."},
  "route": {"distance_miles": 778.8, "duration_minutes": 0.0, "geometry": {"type": "LineString", "coordinates": ["..."]},
            "geometry_detail": "full", "geometry_tolerance_meters": null},
  "vehicle": {"range_miles": 500.0, "mpg": 10.0, "tank_capacity_gallons": "50.000",
              "starting_fuel_gallons": "50.000", "starting_fuel_price_per_gallon": "3.199"},
  "fuel_plan": {
    "currency": "USD",
    "stops": [
      {"sequence": 1,
       "station": {"opis_id": 60540, "name": "CIRCLE K #2706340", "address": "I-20, EXIT 533",
                   "city": "Canton", "state": "TX", "latitude": 32.554245, "longitude": -95.863534},
       "location": {"accuracy": "city", "source": "census_gazetteer_places_2010", "approximate": true,
                    "uncertainty_miles": 1.4, "distance_from_route_miles": 3.6},
       "route_mile": 56.9, "price_per_gallon": "2.77566666", "gallons": "5.685", "cost": "15.78",
       "fuel_on_arrival_gallons": "44.315", "fuel_on_departure_gallons": "50.000"},
      {"sequence": 2,
       "station": {"opis_id": 64558, "name": "MR FUEL #1203", "address": "I-20, EXIT 129",
                   "city": "Meridian", "state": "MS", "latitude": 32.384191, "longitude": -88.68944},
       "location": {"accuracy": "city", "source": "census_gazetteer_places_2010", "approximate": true,
                    "uncertainty_miles": 4.1, "distance_from_route_miles": 0.07},
       "route_mile": 496.3, "price_per_gallon": "2.81233333", "gallons": "22.195", "cost": "62.42",
       "fuel_on_arrival_gallons": "6.055", "fuel_on_departure_gallons": "28.250"}
    ],
    "summary": {
      "number_of_stops": 2,
      "total_gallons_consumed": "77.880",
      "starting_fuel_used_gallons": "50.000",
      "total_gallons_purchased": "27.880",
      "total_purchase_cost": "78.20",
      "fuel_remaining_at_destination_gallons": "0.000",
      "starting_fuel_value": "159.95",
      "estimated_total_fuel_cost": "238.15",
      "estimated_total_fuel_cost_status": "calculated",
      "cost_note": "Purchases ($78.20) plus 50.000 gal of starting fuel valued at $3.199/gal."
    },
    "stop_policy": null,
    "candidates": {"corridor_miles": 5.0, "stations_in_search_area": 242, "stations_on_route": 111}
  },
  "meta": {"provider": "osrm", "attribution": "…", "cached": false, "routing_requests": 1,
           "timings_ms": {"route": 95.82, "station_matching": 20.25, "optimization": 0.33}}
}
```

**Reading the numbers**

* Gallons are rounded to 0.001 per stop. Their sum can differ from full-precision consumption
  by small rounding amounts (0.002 gal on the live 17-stop route). Replay validation uses raw
  quantities; displayed values are not exact physical instructions.
* `total_gallons_consumed` = route miles ÷ mpg (778.8 ÷ 10 = 77.88).
* Starting fuel is used first (it is already paid for): `starting_fuel_used_gallons` =
  min(starting fuel, consumed); `total_gallons_purchased` = consumed − starting fuel used.
* `cost` per stop = `price_per_gallon` × `gallons` (gallons rounded to 0.001), rounded half-up to
  the cent. `total_purchase_cost` is the sum of the stop costs, so the lines add up exactly.
* `total_purchase_cost` is money spent at the recommended stops only. The starting tank is not
  free, but its price is unknown, so `starting_fuel_value` and `estimated_total_fuel_cost`
  (= purchases + starting fuel used × `starting_fuel_price_per_gallon`) are `null` and
  `estimated_total_fuel_cost_status` is `"unavailable"` unless that price is supplied (or no
  starting fuel was used). `cost_note` explains the figures in one sentence.
* Money and gallons are decimal strings (`"78.20"`, `"27.880"`); prices keep the CSV's
  precision (up to 8 decimals, at least 3). Miles and coordinates are numbers.
* Station positions are **town-level approximations** (`location.approximate: true`). Road access
  and detour distance to the actual pump are not checked; `distance_from_route_miles` is the
  straight-line distance from the town point to the route.

**Additional errors**

| Status | `code` | When |
|--------|--------|------|
| 400 | `invalid` | `vehicle` not an object, unknown key, non-numeric or out-of-range value, starting fuel above tank capacity, starting price outside $0.50–$20.00 |
| 422 | `no_feasible_fuel_plan` | Some stretch is longer than the vehicle can drive: `details` gives `from_mile`, `to_mile`, `gap_miles`, `max_reach_miles` |
| 500 | `internal_error` | Unexpected error; logged server-side, no internals in the response |

All `/routes/` errors apply too. A plan is only returned after it has been replayed mile by
mile and checked (tank never below 0 or above capacity, stops in route order).

## Running the dashboard

With Django running and stations imported, open another terminal:

```bash
cd frontend
npm ci
npm run dev
```

Open `http://localhost:3000`. The API defaults to `http://127.0.0.1:8000`;
`NEXT_PUBLIC_API_BASE_URL` overrides it. Allow the browser origin in Django CORS settings.
Run `npm test`, `npm run typecheck`, `npm run lint` and `npm run build` in `frontend/`.
The current suite has 416 backend tests and 36 frontend tests. Unit tests use mocks;
[M7 live evidence](docs/qa/m7-live-results.json) and browser checks are separate.
See [frontend setup](frontend/README.md) for map dependencies and behavior.

## Project structure

```
routefuel/
├── backend/
│   ├── config/             settings, test settings, root URLs, WSGI/ASGI
│   ├── apps/
│   │   ├── core/           health endpoint, error envelope
│   │   ├── routing/        location resolution, OSRM client, route cache, /routes/ (M2),
│   │   │                   /routes/optimize/ and fuel-plan assembly (M3)
│   │   ├── fuel/           FuelStation model, CSV importer, offline geolocation,
│   │   │                   bounding-box station queries, management commands
│   │   └── optimization/   route geometry + fuel optimiser, pure Python (M3)
│   ├── tests/              pytest suite
│   ├── data/               fuel-price CSV; reference/ Census gazetteer + US state polygons
│   ├── manage.py
│   ├── requirements.txt    runtime dependencies
│   ├── requirements-dev.txt
│   ├── pyproject.toml      Ruff configuration
│   └── pytest.ini
├── frontend/               Next.js dashboard (M5–M6)
├── docs/
│   ├── architecture.md
│   └── milestones.md
├── .env.example
└── README.md
```

## Acceptance criteria

Milestone checklists and their verification results are in [docs/milestones.md](docs/milestones.md).

See [docs/architecture.md](docs/architecture.md) for design decisions and data limitations.
