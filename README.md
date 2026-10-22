# RouteFuel

A Django REST API that plans a US driving route and chooses where to buy fuel so the trip
costs as little as possible, using the supplied fuel-price CSV. A Next.js dashboard and the
Django admin sit on top of the same API. Built for the Spotter AI Backend Django Engineer
assessment.

> Station positions are approximate town points from the US Census gazetteer, not verified
> pump locations. Prices are a static snapshot, and the model keeps no reserve fuel. Treat
> results as planning estimates.

**Contents:** [Requirements](#assessment-requirements) · [Features](#implemented-features) ·
[Stack](#technology-stack) · [Architecture](#system-architecture) · [Setup](#prerequisites) ·
[API](#api-endpoints) · [Optimizer](#fuel-optimization-approach) · [Performance](#route-caching-and-performance) ·
[Tests](#automated-testing) · [Admin](#django-admin) · [Limitations](#known-limitations) ·
[Docs](#documentation)

## Assessment requirements

| Requirement | Where it is met |
|---|---|
| Django API with US start and finish | `POST /api/v1/routes/optimize/` — `"City, ST"` or coordinates, US-only |
| Route suitable for a map | GeoJSON `LineString` in `route.geometry` |
| Cost-effective fuel stops, multiple stops | Minimum-purchase-cost optimizer over stations along the route |
| Use the supplied fuel prices | `backend/data/fuel-prices-for-be-assessment.csv`, imported into SQLite |
| 500-mile range, 10 MPG | Defaults (50-gallon tank); configurable per request |
| Total money spent on fuel | `fuel_plan.summary.total_purchase_cost` (see [costs](#purchases-versus-whole-trip-cost)) |
| Free routing API, few calls | Public OSRM; one request per new route, zero when cached |
| Fast responses | Local processing in tens of milliseconds; see [performance](#route-caching-and-performance) |
| Latest stable Django | Django 6.1.2 |

## Implemented features

- Three JSON endpoints: health, route only, and route with an optimized fuel plan.
- Offline location resolution (Census places, US state polygons). No geocoding service.
- One OSRM request per uncached route, a seven-day database route cache, and coalescing of
  identical concurrent requests.
- An exact minimum-cost refuelling optimizer. Every plan is replayed to check fuel balance and
  capacity. An opt-in "practical stops" policy drops stops that save less than a threshold.
- Configurable vehicle range, MPG, starting fuel and starting-fuel price.
- CLI import of the employer CSV with duplicate merging and offline town-level geolocation.
- Django admin for station data, including a previewed CSV/XLSX import.
- A Next.js dashboard with a MapLibre route map, fuel-stop cards and a cost summary.
- A Postman collection with a local runner.

## Technology stack

| Layer | Choice |
|---|---|
| Backend | Python 3.12+ (checked on 3.13), Django 6.1.2, Django REST Framework 3.18, django-cors-headers, httpx, openpyxl |
| Storage and cache | SQLite; Django database cache for routes |
| Routing | OSRM HTTP API (public demo server by default) |
| Frontend | Node.js 20.9+, Next.js 16, React 19, TypeScript, Tailwind CSS 4, MapLibre GL 5 |
| Quality | pytest + pytest-django, Ruff, Vitest + Testing Library, `node --test`, ESLint, `tsc` |

## System architecture

```
Next.js dashboard / Postman / curl
            │  JSON (CORS limited to the dashboard origins)
            ▼
Django REST API  /api/v1/
  routing        request validation → offline location resolution → cached OSRM route
                 → station matching along the route → fuel plan payload
  optimization   pure-Python refuelling optimizer and route-geometry helpers
  fuel           FuelStation model, CSV importer, offline geolocation, admin import
  core           health endpoint, error envelope, raw-JSON renderer, admin site
            │
            ├── SQLite: stations, route cache, admin users and sessions
            └── OSRM: at most one HTTP request per uncached route
```

Full detail: [architecture snapshot](docs/project-architecture-snapshot.md) ·
[design notes](docs/architecture.md).

## Project structure

```
backend/
  config/            settings, URLs, WSGI/ASGI, test settings
  apps/core/         health view, exception handler, renderer, admin site
  apps/routing/      serializers, views, locations, OSRM provider, cache service, fuel_plans
  apps/optimization/ optimizer.py, geometry.py
  apps/fuel/         models, importer, geolocation, queries, admin, admin import
  data/              fuel-price CSV and reference datasets (see data/reference/SOURCE.md)
  templates/, static/  admin customization
  tests/             pytest suite
frontend/            Next.js dashboard (src/, tests/)
docs/                API contract, architecture, Postman, QA reports, Loom script
```

## Prerequisites

- Python 3.12 or newer, with `venv`
- Node.js 20.9 or newer and npm (checks ran on Node 20.20 and 22)
- Internet access to install dependencies, request uncached routes from OSRM and load the
  dashboard's CARTO basemap. No API keys are needed.

## Backend installation

From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate                  # Windows: .venv\Scripts\activate
python -m pip install -r backend/requirements-dev.txt
```

## Environment configuration

```bash
cp .env.example .env
python -c "from django.core.management.utils import get_random_secret_key as k; print(k())"
```

Put the generated value in `DJANGO_SECRET_KEY` in `.env`. Never commit `.env`. The settings
read the root `.env`; real environment variables take precedence.

| Variable | Default | Notes |
|---|---|---|
| `DJANGO_SECRET_KEY` | none | Required when `DJANGO_DEBUG` is false |
| `DJANGO_DEBUG` | `false` | `.env.example` sets `true` for local development |
| `DJANGO_ALLOWED_HOSTS` | `localhost,127.0.0.1` | |
| `DJANGO_CORS_ALLOWED_ORIGINS` | `http://localhost:3000,http://127.0.0.1:3000` | Keep **both** origins: `npm run dev` binds to `127.0.0.1` |
| `DJANGO_SECURE_COOKIES` | `true` when DEBUG is off | Admin session and CSRF cookies are HTTPS-only |
| `ROUTEFUEL_DASHBOARD_URL` | `http://localhost:3000` | Link shown in the admin |
| `ROUTING_BASE_URL` | `https://router.project-osrm.org` | Any OSRM-compatible server |
| `ROUTING_TIMEOUT` | `10` | Seconds; connect timeout capped at 5 |
| `ROUTING_USER_AGENT` | RouteFuel identifier | Required by the OSRM demo usage policy |
| `ROUTE_CACHE_TTL` | `604800` | Seconds (seven days) |
| `FUEL_CORRIDOR_MILES` | `5` | Plus each town point's uncertainty radius |

Invalid values stop Django at startup with a clear message.

## Database setup

```bash
cd backend
python manage.py migrate
python manage.py createsuperuser          # optional, for the admin; choose your own credentials
```

## Fuel data import

```bash
python manage.py import_fuel_prices       # imports the CSV, then geolocates stations offline
```

The supplied 8,151 rows produce **6,626 US stations**. 6,228 have town-level coordinates and
398 stay unresolved; unresolved stations are excluded from route matching. The other rows
are 620 Canadian stations (skipped as out of scope) and 905 duplicate rows merged into existing
stations. Re-running it inserts nothing new.

Useful options: `--dry-run`, `--skip-geolocation`, `--file <path>`.
`python manage.py geolocate_stations --force` rebuilds coordinates from the local gazetteer.

**Data files.** The fuel-price CSV was provided by the employer for this assessment. The Census
gazetteer and Natural Earth state boundaries are public domain; provenance and checksums are
in [`backend/data/reference/SOURCE.md`](backend/data/reference/SOURCE.md). If the CSV is not
included in your copy of the repository, place it at `backend/data/fuel-prices-for-be-assessment.csv`
or pass `--file /path/to/file.csv`. The test suite does not need it.

## Starting Django

```bash
python manage.py runserver 127.0.0.1:8000
curl http://127.0.0.1:8000/api/v1/health/      # {"status":"ok","service":"routefuel-api"}
```

`/` redirects to the admin at `/admin/`.

## Starting Next.js

In a second terminal:

```bash
cd frontend
npm ci
npm run dev                                    # http://127.0.0.1:3000
```

The API address defaults to `http://127.0.0.1:8000`. To change it, copy
`frontend/.env.example` to `frontend/.env.local`, edit `NEXT_PUBLIC_API_BASE_URL` and restart
Next.js. The dashboard origin you open, `http://127.0.0.1:3000` or `http://localhost:3000`,
must be listed in `DJANGO_CORS_ALLOWED_ORIGINS`. More: [frontend/README.md](frontend/README.md).

## API endpoints

| Method | Path | Returns |
|---|---|---|
| GET | `/api/v1/health/` | Liveness only (no database or provider check) |
| POST | `/api/v1/routes/` | Resolved locations, route distance, duration and GeoJSON geometry |
| POST | `/api/v1/routes/optimize/` | The same plus vehicle, ordered fuel stops and a cost summary |

No authentication. JSON in and out. Errors use a single envelope:
`{"error": {"code", "message", "details"}}`. The status is 400 for invalid input; 422 for
unknown, ambiguous, out-of-US or undrivable locations and infeasible fuel plans; and 502, 503
or 504 for routing-provider failures. Full field reference: [API contract](docs/api-contract.md).

## Example API requests

```bash
curl -s http://127.0.0.1:8000/api/v1/routes/optimize/ \
  -H 'Content-Type: application/json' \
  -d '{"start": "Dallas, TX", "finish": "Atlanta, GA", "geometry_detail": "simplified"}'
```

Optional fields:
`"vehicle": {"range_miles": 500, "mpg": 10, "starting_fuel_gallons": 50, "starting_fuel_price_per_gallon": "3.199"}`
and `"stop_policy": {"min_savings_per_stop": "2.00"}`. Locations can also be
`{"latitude": 32.7767, "longitude": -96.797}`.

Abridged live response (22 October 2026; geometry and the second and third stops omitted):

```json
{
  "route": {"distance_miles": 778.8, "duration_minutes": 843.9, "geometry": {"type": "LineString", "coordinates": ["..."]}},
  "vehicle": {"range_miles": 500, "mpg": 10, "tank_capacity_gallons": "50.000", "starting_fuel_gallons": "50.000", "starting_fuel_price_per_gallon": null},
  "fuel_plan": {
    "stops": [{"sequence": 1, "station": {"opis_id": 60540, "name": "CIRCLE K #2706340", "city": "Canton", "state": "TX"},
               "route_mile": 57.2, "price_per_gallon": "2.77566666", "gallons": "5.718", "cost": "15.87"}],
    "summary": {"number_of_stops": 3, "total_gallons_consumed": "77.880", "starting_fuel_used_gallons": "50.000",
                "total_gallons_purchased": "27.880", "total_purchase_cost": "78.19",
                "estimated_total_fuel_cost": null, "estimated_total_fuel_cost_status": "unavailable"}
  },
  "meta": {"provider": "osrm", "cached": false, "routing_requests": 1}
}
```

## Fuel optimization approach

- **Vehicle:** tank capacity = range ÷ MPG = 500 ÷ 10 = **50 gallons**. The trip starts with a
  full tank unless `starting_fuel_gallons` says otherwise.
- **Candidates:** stations with coordinates whose town point lies within 5 miles of the
  route, plus that town's uncertainty radius. Each candidate gets a mile marker along the route.
- **Objective:** minimize money spent at stations for the fixed route. Fuel bought can be any
  continuous quantity; the tank can never exceed capacity or run dry before the next
  station or the destination.
- **Algorithm:** walk stations in route order, keeping the tank as fuel "lots". At each
  station, refund any lot bought at a higher price, then notionally fill up. Fuel actually
  sold is what gets burned. This is the classical optimal greedy for the single-route
  problem: in effect, buy just enough to reach a cheaper reachable station, otherwise fill
  up. Code: [`backend/apps/optimization/optimizer.py`](backend/apps/optimization/optimizer.py).
- **Checks:** each plan is replayed (order, no dry tank, capacity, fuel balance). Tests compare
  it with an independent dynamic-programming solver, and the audit compared it with a linear
  program on 4,000 random and three real routes ([audit](docs/final-pre-submission-audit.md)).
- **Feasibility:** if a gap between stations (or to the destination) exceeds the range, the API
  returns `422 no_feasible_fuel_plan` with the gap location.
- **Practical stops (optional):** `stop_policy.min_savings_per_stop` greedily removes stops that
  save less than the threshold. The default objective is unchanged when it is omitted.

### Purchases versus whole-trip cost

- `total_purchase_cost` is **money spent at the recommended stops** during the trip. It does
  **not** include the fuel already in the tank at departure. That fuel is not free; it was
  simply paid for before the trip.
- With a starting-fuel price (`starting_fuel_price_per_gallon`), the API also returns
  `starting_fuel_value` and `estimated_total_fuel_cost`, the economic cost of all fuel burned.
  Without it, the whole-trip status is `unavailable` and `cost_note` explains why.
- Example, Dallas–Atlanta, 77.88 gallons burned:

  | Settings | Purchases | Whole-trip cost |
  |---|---|---|
  | Full tank, no starting price | $78.19 | unavailable |
  | Full tank at $3.00/gal | $78.19 | $228.19 |
  | Empty tank | $217.37 (5 stops) | $217.37 |

- Money and prices are `Decimal`. Gallons display to 0.001, and each stop's cost is rounded
  half-up to the cent; the total is the sum of those line items.

## Route caching and performance

- One OSRM request per uncached route; zero for cached routes. No routing request is made per
  station. Successful routes are cached in the database for seven days, keyed by direction and
  rounded coordinates.
- `meta.cached`, `meta.routing_requests` and `meta.timings_ms` (route, station matching,
  optimization) are returned with every optimized response.

Measured on 22 October 2026 against live OSRM, through the local Django server on a MacBook.
These are single observations, not guarantees.

| Request | Total | OSRM (network) | Local processing |
|---|---|---|---|
| Dallas → Atlanta, uncached | 984 ms | 947 ms | ≈ 20 ms station matching + 0.3 ms optimization |
| Dallas → Atlanta, cached | 28 ms | — | 0 provider calls |
| New York → Los Angeles, uncached | 3.59 s | 3.54 s | 29 ms matching + 0.6 ms optimization |
| Dallas → Austin, uncached | 374 ms | 351 ms | 14 ms |

Results on those runs: Dallas–Atlanta 778.8 mi, 3 stops, $78.19. New York–Los Angeles
2,810.37 mi, 17 stops, $698.65, or 11 stops and $700.74 with the `$2` practical-stop policy.
Dallas–Austin 195.6 mi, no stop needed. Provider data can change these figures.

## Automated testing

```bash
cd backend
python manage.py check
python manage.py makemigrations --check --dry-run
pytest -q                      # 511 tests; network access is blocked in tests
ruff check . && ruff format --check .
python manage.py verify_routing    # optional live OSRM check (fresh route + cache reuse)

cd ../frontend
npm test                       # node --test (7) + Vitest (29)
npm run typecheck
npm run lint
npm run build
```

Latest verified counts are in the [final snapshot report](docs/final-snapshot-report.md).
`python manage.py benchmark_api` measures application overhead with a stand-in provider.

## Django admin

`http://127.0.0.1:8000/admin/` uses native Django authentication, sessions, CSRF protection
and model permissions, with a RouteFuel theme. Station records can be searched by name, OPIS ID,
city or address and filtered by state and geolocation accuracy or source. Admin sessions never
authenticate the public API. Details: [admin enhancement](docs/admin-enhancement.md).

## CSV/XLSX import

**Fuel stations → Import Fuel Stations** uploads a `.csv` (UTF-8) or `.xlsx` file
(5 MB / 20,000 rows) or downloads an Excel template.

- A preview shows new, updated (current → new values), unchanged, invalid and duplicate rows
  before anything is saved.
- Stations are matched only by OPIS Truckstop ID. Blank cells keep stored values.
- Confirmation applies the previewed changes in one transaction and can be done once.
- New or moved stations are placed at their town offline.
- Requires the add and/or change fuel-station permission.

Details: [admin fuel-station import](docs/admin-fuel-import.md).

## Known limitations

- Station coordinates are Census town points: road access, exits, detours and truck
  restrictions are not verified, and a station can be matched to the wrong pass of a route.
- Prices are a static snapshot; consumption is linear at constant MPG; there is no fuel reserve,
  so a plan may arrive with an empty tank.
- `total_purchase_cost` excludes the starting tank; whole-trip cost needs a starting price.
- The public OSRM demo server is rate-limited (about 1 request per second) and has no SLA.
  Point `ROUTING_BASE_URL` at your own OSRM server for heavier use.
- The practical-stop policy is greedy, not a minimum-stop solver.
- SQLite and the bundled settings are for local evaluation, not a production deployment.

## Postman demonstration

Import `docs/postman/RouteFuel.postman_collection.json` and the local environment, set
`base_url` to `http://127.0.0.1:8000` and use a 1,100 ms runner delay. Eight requests cover
health, routing, optimization, a long route, a custom vehicle and the 400/422 error cases.
Without Postman: `python docs/postman/run_collection.py --base-url http://127.0.0.1:8000`
(checks status codes only). Guide: [docs/postman/README.md](docs/postman/README.md).

## Loom video

Link: *to be added after recording.* Script (target 4:50): [docs/loom-demo-script.md](docs/loom-demo-script.md).

## Documentation

| Document | Contents |
|---|---|
| [API contract](docs/api-contract.md) | Request/response fields, errors, caching |
| [Architecture snapshot](docs/project-architecture-snapshot.md) | Module-by-module description of the implementation |
| [Architecture notes](docs/architecture.md) | Design decisions and trade-offs by milestone |
| [Admin enhancement](docs/admin-enhancement.md), [Admin import](docs/admin-fuel-import.md) | Admin security, UI and spreadsheet import |
| [Final audit](docs/final-pre-submission-audit.md), [Snapshot report](docs/final-snapshot-report.md) | Latest verification evidence |
| [M7 QA report](docs/m7-final-qa-report.md), [Milestones](docs/milestones.md) | Historical QA and progress |
| [Postman guide](docs/postman/README.md), [Loom script](docs/loom-demo-script.md) | Demonstration material |
| [Submission checklist](docs/submission-checklist.md), [GitHub steps](docs/github-readiness.md) | Publication steps |
| [Data sources](backend/data/reference/SOURCE.md) | Reference dataset provenance |
