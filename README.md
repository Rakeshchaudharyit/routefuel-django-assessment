# RouteFuel

A Django REST API that plans a driving route between two US locations and recommends where to
buy fuel so the trip costs as little as possible. Built as the backend assessment for the
Backend Django Engineer role at Spotter AI.

> **Status:** M0 (foundation), M1 (fuel data) and M2 (routing) complete. Fuel-stop optimisation
> arrives in M3 — see [docs/milestones.md](docs/milestones.md).

## Assessment requirements

The finished API will:

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

cd backend
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
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
| `DJANGO_CORS_ALLOWED_ORIGINS` | `http://localhost:3000` | Origins allowed to call `/api/*` |
| `ROUTING_BASE_URL` | `https://router.project-osrm.org` | OSRM-compatible routing server |
| `ROUTING_TIMEOUT` | `10` | Routing request timeout in seconds (must be > 0; connect capped at 5) |
| `ROUTING_USER_AGENT` | `RouteFuel/0.2 (Spotter AI assessment; …)` | User-Agent sent to the routing server (required by the OSRM usage policy) |
| `ROUTE_CACHE_TTL` | `604800` (7 days) | Seconds a successful route stays cached (must be > 0) |

Invalid values (e.g. `DJANGO_DEBUG=maybe`, `ROUTING_TIMEOUT=0`, `ROUTE_CACHE_TTL=-1`) fail fast at startup with a clear message.

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
routing server is reachable — check that with the curl examples below against `runserver`.

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

Response (`200`). Distance and duration below are what the public OSRM server returned for this
pair on 2026-10-21; the geometry is shortened here — the real one has the full road path:

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
  and none on a hit.
* **Cache:** successful routes are stored in Django's database cache (table `routefuel_cache`
  in the same SQLite file, created by `migrate`) for `ROUTE_CACHE_TTL` seconds. The key is the
  provider + server + coordinates rounded to 5 decimals (~1 m), direction-sensitive, so
  `"Dallas, TX"`, `"dallas, texas"` and the same coordinates share one entry. Errors are never
  cached. If the cache table is unavailable the request still succeeds, just uncached.

## Project structure

```
routefuel/
├── backend/
│   ├── config/             settings, test settings, root URLs, WSGI/ASGI
│   ├── apps/
│   │   ├── core/           health endpoint, error envelope
│   │   ├── routing/        location resolution, OSRM client, route cache, /routes/ (M2)
│   │   ├── fuel/           FuelStation model, CSV importer, offline geolocation,
│   │   │                   bounding-box station queries, management commands
│   │   └── optimization/   fuel-stop optimiser (M3)
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
