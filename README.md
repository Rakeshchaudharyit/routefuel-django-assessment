# RouteFuel

RouteFuel is a Django REST API and Next.js dashboard for planning US driving routes and
minimum-cost fuel purchases using the supplied station-price CSV. Built for the Spotter AI
Backend Django Engineer assessment.

M0–M7 are implemented and audited. M8 submission materials are prepared locally; GitHub
publication and the Loom recording remain pending. See the [submission checklist](docs/submission-checklist.md).

**Station locations are approximate town points, not verified pump locations.** Road access,
detours and truck restrictions are unverified. Prices are a static snapshot. The model has
no reserve fuel and may arrive empty; confirm actual stops and fuel margins before travel.

[API contract](docs/api-contract.md) · [Architecture](docs/architecture.md) ·
[M7 QA report](docs/m7-final-qa-report.md) · [Postman guide](docs/postman/README.md)

## Assessment requirements

The assessment asks for an API that accepts US start/finish locations, returns a driving
route suitable for a map, selects cost-effective stations from the supplied CSV, supports
multiple stops, and reports fuel expenditure. Defaults are a 500-mile range and 10 MPG.
External routing calls should be minimized, responses fast, and errors handled clearly.
The dashboard demonstrates the same API; it does not duplicate optimization in the browser.

## Technology and prerequisites

| Component | Choice |
|---|---|
| Backend | Python 3.12+, Django 6.1, Django REST Framework 3.18 |
| Storage | SQLite; Django database cache |
| Routing | OSRM-compatible HTTP API via httpx |
| Frontend | Node.js 20.9+, Next.js 16, React 19, TypeScript, Tailwind, MapLibre |
| Checks | pytest, Ruff, Vitest/Testing Library, TypeScript, ESLint |

Checks ran on Python 3.13 and Node.js 20.20.2. Python dependencies use bounded version ranges;
frontend dependencies are resolved in `frontend/package-lock.json`. Internet is required to
install dependencies, obtain uncached routes and load the CARTO basemap. OSRM and CARTO do
not require private API keys for this demo.

## Backend setup

Start in the repository root. If cloning after publication, use the public repository URL
provided with the submission.

```bash
python3 -m venv .venv
source .venv/bin/activate             # Windows: .venv\Scripts\activate
python -m pip install -r backend/requirements-dev.txt
cp .env.example .env
```

Edit the root `.env` and replace the placeholder `DJANGO_SECRET_KEY` with a random value.
The example enables DEBUG only for local development. A key can be generated after installing
Django with `python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"`.
Never commit the real `.env`.

```bash
cd backend
python manage.py migrate             # creates application and route-cache tables
python manage.py import_fuel_prices   # imports CSV and preprocesses approximate coordinates
python manage.py runserver 127.0.0.1:8000
```

From another terminal: `curl http://127.0.0.1:8000/api/v1/health/` returns
`{"status":"ok","service":"routefuel-api"}`. Health does not check the station database or OSRM.

The import is idempotent. The supplied 8,151 CSV rows yield **6,626 US stations**, with
**6,228 town-level coordinates** and **398 unresolved stations** excluded from matching.
Canadian rows are out of scope and duplicate rows are merged. No station has a verified
address coordinate. Reference datasets are included, so preprocessing needs no geocoding
network request. See [data sources](backend/data/reference/SOURCE.md).

From `backend/`, with the virtual environment active:

```bash
python manage.py import_fuel_prices --dry-run
python manage.py geolocate_stations --force   # optional: rebuild coordinates from local reference data
```

## Frontend setup

In a separate terminal, start at the repository root:

```bash
cd frontend
npm ci
npm run dev
```

Open `http://localhost:3000`. The public API URL defaults to `http://127.0.0.1:8000`.
To override it, copy `frontend/.env.example` to `frontend/.env.local`, edit the URL and restart
Next.js. These paths are relative to the repository root. Never put secrets in `NEXT_PUBLIC_*`
settings. Django CORS must allow the browser's origin. See [frontend details](frontend/README.md).

## Configuration

Environment variables override the root `.env`; the frontend separately reads its own
`.env.local` at development/build time.

| Backend variable | Default / meaning |
|---|---|
| `DJANGO_SECRET_KEY` | Required when DEBUG is off; set a real value locally |
| `DJANGO_DEBUG` | `false`; the example opts into local development mode |
| `DJANGO_ALLOWED_HOSTS` | `localhost,127.0.0.1` |
| `DJANGO_CORS_ALLOWED_ORIGINS` | `http://localhost:3000,http://127.0.0.1:3000` |
| `ROUTING_BASE_URL` | `https://router.project-osrm.org` |
| `ROUTING_TIMEOUT` | `10` seconds; connect timeout capped at 5 seconds |
| `ROUTING_USER_AGENT` | Identifies RouteFuel to the provider |
| `ROUTE_CACHE_TTL` | `604800` seconds (seven days) |
| `FUEL_CORRIDOR_MILES` | `5`, plus each town's location uncertainty |

Invalid or non-finite positive settings fail at startup. Local development settings are not
a production deployment configuration.

## API usage

| Method | Endpoint | Returns |
|---|---|---|
| GET | `/api/v1/health/` | Liveness |
| POST | `/api/v1/routes/` | Driving route and GeoJSON LineString |
| POST | `/api/v1/routes/optimize/` | Route, ordered fuel purchases and cost summary |

Both POST endpoints accept `"City, ST"` / `"City, State"` or
`{"latitude":32.7767,"longitude":-96.797}` for either location. City names resolve offline to
Census place points. Coordinates must be within the supported 50 states and DC.

```bash
curl -s http://127.0.0.1:8000/api/v1/routes/ \
  -H 'Content-Type: application/json' \
  -d '{"start":"Dallas, TX","finish":"Atlanta, GA","geometry_detail":"simplified"}'

curl -s http://127.0.0.1:8000/api/v1/routes/optimize/ \
  -H 'Content-Type: application/json' \
  -d '{"start":"Dallas, TX","finish":"Atlanta, GA","geometry_detail":"simplified",
       "vehicle":{"range_miles":500,"mpg":10,"starting_fuel_gallons":50,
                  "starting_fuel_price_per_gallon":"3.199"}}'
```

Abridged optimized response from the live Dallas–Atlanta route (22 October 2026). Geometry,
station details and other fields are omitted here; the [API contract](docs/api-contract.md)
describes the full wire format. Results can change with provider data.

```json
{
  "route": {"distance_miles": 778.8, "duration_minutes": 843.9},
  "fuel_plan": {
    "summary": {
      "number_of_stops": 3,
      "total_gallons_consumed": "77.880",
      "starting_fuel_used_gallons": "50.000",
      "total_gallons_purchased": "27.880",
      "total_purchase_cost": "78.19",
      "fuel_remaining_at_destination_gallons": "0.000",
      "starting_fuel_value": "159.95",
      "estimated_total_fuel_cost": "238.14",
      "estimated_total_fuel_cost_status": "calculated"
    }
  }
}
```

All API errors use `{"error":{"code":"...","message":"...","details":null}}`, with field
errors or domain context in `details` when applicable. Invalid inputs return 400; unknown,
ambiguous or undrivable locations and infeasible fuel plans return 422; provider failures
return 502/503/504. See the contract for exact error codes and request constraints.

## Fuel model and costs

- Range ÷ MPG determines usable capacity: 500 ÷ 10 = 50 gallons. Starting fuel defaults to
  a full tank and can be configured.
- On a fixed route, the optimizer buys enough to reach a cheaper reachable station; otherwise
  it fills. It implements this through fuel lots and refunds of unused purchases, then replays
  the plan to verify order, fuel balance and capacity.
- The objective minimizes continuous fuel purchase cost before display rounding. It does not
  minimize stops, driving distance, detours, time or line-by-line rounded cents.
- `total_purchase_cost` covers only fuel bought at stops. Starting fuel is already owned,
  not free. Whole-trip cost is unavailable unless its price is supplied or none is consumed.
- Prices retain CSV precision. Gallons display to 0.001; each purchase is HALF_UP rounded to
  cents and the total equals the sum of line costs. Displayed fuel balances can differ slightly
  due to per-stop rounding (0.002 gallons in the audited 17-stop route).

Optional `"stop_policy":{"min_savings_per_stop":"2.00"}` removes stops whose incremental
savings are below the threshold, reoptimizing each time. This is a greedy practical rule,
not a minimum-stop solver or a total extra-cost budget. Live New York–Los Angeles returned
17 stops / $698.65 by default and 11 stops / $700.74 with this policy (+$2.09). Five stops
are feasible in the approximate candidate model. Rounded `extra_cost` can be negative by a
cent for effectively equal exact-cost plans.

## Routing, performance and caching

Each uncached route uses one OSRM request; cached routes use zero. Location resolution,
station filtering and optimization run locally, with no per-station routing calls. Successful
routes share a direction-sensitive database cache; errors are not cached. Identical concurrent
successes are coalesced, with documented failure/cache-fallback limits.

The public OSRM demo is for light use: space requests at least 1.1 seconds apart and retain
attribution. Use a separately operated OSRM instance for heavier use. There are no automatic
HTTP retries in the provider client. `meta.cached`, `meta.routing_requests` and optimization
stage timings explain each result. `geometry_detail: "simplified"` reduces display geometry;
fuel matching always uses its separate full-route processing.

M7 single-run measurements, including real network calls through Django's in-process client:
fresh API requests 469–1,039 ms, cached requests 2.9–5.1 ms. New York had 399 candidates and
0.61 ms pure optimization time. These are not latency guarantees or HTTP percentiles.
[Full evidence and measurement boundaries](docs/m7-final-qa-report.md#performance).

## Tests and live verification

From the repository root, activate `.venv`, then:

```bash
cd backend
python manage.py check
python manage.py makemigrations --check --dry-run
pytest -q
ruff check .
ruff format --check .
python manage.py verify_routing       # real provider; makes up to two calls, spaced apart
```

In `frontend/`:

```bash
npm test
npm run typecheck
npm run lint
npm run build
```

M8 reran **416 backend tests and 36 frontend tests**, plus all checks above. Automated tests
block/mock external routing; the live verification command is separate. The optimizer matches
an independently formulated DP over 11,300 seeded cases at integer, tenth- and thousandth-gallon
scales. Fresh database migrations/import/reimport also passed. See [M7 QA](docs/m7-final-qa-report.md)
and [M8 checklist](docs/submission-checklist.md) for evidence and limits.

Optional benchmark commands from `backend/`:

```bash
python manage.py benchmark_api                   # synthetic route provider; application overhead
python manage.py benchmark_api --live --runs 5    # real provider; light use only
```

## Postman and demonstration

Import the collection and local environment under `docs/postman/`, select that environment,
and set `base_url`. Use a **1,100 ms request delay** in Collection Runner. The collection
covers health, routing, optimization, a long route, custom vehicle, validation and unreachable
and infeasible journeys. [Import/demo instructions](docs/postman/README.md).

Without Postman, run from the repository root with Django running:

```bash
python docs/postman/run_collection.py --base-url http://127.0.0.1:8000
```

This runner sends the eight requests, spaces them apart and checks HTTP statuses; it does
not execute the collection's JavaScript assertions.

The [4:50 Loom script](docs/loom-demo-script.md) and [GitHub publication steps](docs/github-readiness.md)
are prepared for manual review. No repository has been created or pushed and no video recorded.

## Known limitations

Town geolocation can admit or exclude the wrong station, merge several markers, or project a
station onto the wrong pass of a looping route. Uncertainty circles are estimates, not error
guarantees. The model assumes all candidate pumps are reachable at their route mile, constant
MPG, static prices, linear fuel consumption and no reserve. It does not optimize the chosen
OSRM path or account for truck restrictions, access, detours, traffic or stop duration.

The lot implementation has an O(n²) worst case despite being fast on this dataset. The optional
stop policy is greedy. An open popup can clip after fitting a cross-country route; reselect or
close it. Dependency advisory scanning timed out during M7, so vulnerability status is
unverified. SQLite, the public provider and local development settings suit this assessment,
not a claim of production readiness.
