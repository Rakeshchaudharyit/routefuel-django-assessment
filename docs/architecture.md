# RouteFuel — Architecture

## Goal

Given a start and finish in the USA, return a driving route (map-ready geometry) plus the
fuel stops and purchases that minimise total fuel cost for a vehicle with a 500-mile range
at 10 MPG, using the employer-provided fuel-price CSV.

## Shape of the system

```
Next.js dashboard (M5–M6)
        │  JSON over HTTP (CORS-limited to the dashboard origin)
        ▼
Django REST API  /api/v1/
  ├── core          health, error envelope, shared validation
  ├── routing       location resolution, OSRM client, route caching
  ├── fuel          CSV import, FuelStation data, offline geolocation, corridor queries
  └── optimization  pure-Python cost minimisation (no I/O)
        │                         │
        ▼                         ▼
   SQLite (stations)        OSRM (one call per uncached route)
```

One Django project, four apps, no services, queues or caches beyond Django's built-in cache.
That is the right size for a three-day assessment and still reads as a real codebase.

### App responsibilities

| App | Owns | Does not own |
|-----|------|--------------|
| `core` | `/health/`, the `{"error": {...}}` envelope, shared validators | business logic |
| `routing` | turning inputs into coordinates; calling OSRM; caching routes | prices, optimisation |
| `fuel` | the `FuelStation` table, CSV import, "stations near this route" queries | HTTP calls |
| `optimization` | deciding where to stop and how much to buy | database or network access |

`optimization` is kept free of Django models and I/O on purpose: it takes plain data
(route length, stations with mile markers and prices) and returns a plan. That makes it
fast to unit-test against hand-calculated answers.

### Request flow (steps 1–3 built in M2; 4–6 are M3–M4)

1. Validate input (US locations, start ≠ finish).
2. Resolve start/finish to coordinates — from an offline US place index where possible, so no
   external geocoding call is needed.
3. Check the route cache; on a miss, make **one** OSRM `route` call
   (`overview=full&geometries=geojson`).
4. Prefilter stations with a bounding box around the route (indexed lat/lng columns), then
   compute each candidate's distance to the polyline and its mile marker along the route.
5. Run the optimiser on the ordered candidates.
6. Return geometry, distance, stops, gallons per stop, cost per stop and totals.

No routing calls are made per station; all station work is local.

## Configuration

All environment-specific values come from environment variables (see `.env.example`),
optionally loaded from `.env` at the repo root. Defaults are safe: `DEBUG` is off unless enabled,
and a secret key is mandatory whenever `DEBUG` is off. Tests use `config/test_settings.py`,
which pins every value so the suite never depends on a developer's `.env`.

## Error handling

Every DRF-handled error returns:

```json
{"error": {"code": "method_not_allowed", "message": "Method \"POST\" not allowed.", "details": null}}
```

`details` carries field-level validation errors when present. Domain errors are raised as
`apps.core.exceptions.ApiError(status_code, code, message, details)`, which the same handler
renders, so location and routing failures use explicit codes (`ambiguous_location`,
`route_not_found`, `routing_unavailable`, …) and never leak provider responses. The full table
is in the README.

## Fuel data layer (M1)

### Source CSV — measured profile

`backend/data/fuel-prices-for-be-assessment.csv`, UTF-8, 7 columns:
`OPIS Truckstop ID, Truckstop Name, Address, City, State, Rack ID, Retail Price`.

| Check | Finding |
|-------|---------|
| Rows | 8,151; every row has exactly 7 fields |
| Missing values | None in any column. One address is just `","` |
| Untrimmed whitespace | City 1,256 rows, Address 97, Name 3 |
| Station IDs | 6,738 distinct; 678 IDs appear on 2–6 rows (1,413 extra rows) |
| Repeated IDs | Address, city, state and rack always agree; name spelling differs in 226 groups; price differs in 597 groups (max spread $0.90, >$0.10 in 216) |
| Shared locations | 358 address/city/state combinations are used by 759 *different* IDs (e.g. a Love's and a local stop at the same exit) |
| Prices | All parse as decimals; $2.687–$6.399; up to 8 decimal places (averaged values like `3.00733333`) |
| States | 57 codes: 48 US states (no AK, HI, DC) plus 9 Canadian provinces/territories (112 stations, 620 rows) |
| Address quality | 3,762 "highway + exit" (`I-44, EXIT 283 & US-69`), 2,856 highway only (`US-46`), 114 other, **6** with a street number |
| Coordinates | None anywhere in the file |

### Validation and import rules

| Rule | Outcome |
|------|---------|
| Header lacks a required column, file missing, not UTF-8, unparsable | Whole import aborts before any write (`CommandError`) |
| Wrong number of cells in a row | Row rejected: `malformed_row` |
| Blank ID, name, city, state, rack or price | Row rejected: `missing_field` |
| ID / rack not a positive integer (≤ 2³¹−1) | Row rejected: `invalid_id` / `invalid_rack_id` |
| State is a Canadian province | Row **skipped**: `non_us_station` (out of scope; currency unconfirmed) |
| State not one of the 50 states + DC | Row rejected: `invalid_state` |
| Price not a finite decimal, outside $0.50–$20.00, or more than 8 decimals | Row rejected: `invalid_price` (never rounded) |
| Blank or punctuation-only address | Kept with an `incomplete_address` warning (address is not used for geolocation) |

Text is trimmed and whitespace-collapsed; state codes are upper-cased. Every rejected or skipped
row is reported with its CSV line number, ID, reason and detail (`--show-issues N`).

### Duplicate handling

* **One station per OPIS ID.** Rows with the same ID are merged.
* **Conflicting location → reject, don't guess.** If merged rows disagree on address, city,
  state or rack, every row for that ID is rejected as `conflicting_duplicate`. (None in the
  supplied file.)
* **Price:** `retail_price` = lowest listed price; `max_retail_price` and `price_observations`
  keep the spread visible. The file has no dates, so no row can be called "latest". The
  lowest price is the best listed price at that stop; the stored max lets M3/M4 show the range
  or switch policy without re-importing.
* **Name:** most frequent spelling; first seen wins ties.
* **Invalid rows don't sink valid ones:** a bad price row is rejected, and the station is built
  from the remaining valid rows.
* **Same location, different IDs:** kept as separate stations — they are different businesses.

### Re-import semantics

* Upsert by `opis_id` inside one transaction (`bulk_create` + `bulk_update`, batches of 500).
  Any database error rolls back the entire import; `--dry-run` runs everything then rolls back.
* Unchanged stations are not written. Changed stations are updated.
* If a station's address, city or state changes, its coordinates are cleared (back to
  `unresolved`) so stale coordinates are never kept.
* Stations missing from a new file are kept and counted, not deleted.

### Schema — `fuel.FuelStation`

| Field | Type | Notes |
|-------|------|-------|
| `opis_id` | PositiveInteger, **unique** | Natural key |
| `name`, `address`, `city`, `state`, `rack_id` | text / int | Normalised source values |
| `retail_price`, `max_retail_price` | Decimal(10, 8) | Exact source precision |
| `price_observations` | PositiveSmallInteger | Rows merged into this station |
| `latitude`, `longitude` | Float, nullable | WGS84 |
| `geolocation_source` | choice | `""` or `census_gazetteer_places_2010` |
| `geolocation_accuracy` | choice | `unresolved`, `city`, `address` (reserved) |
| `location_uncertainty_miles` | Float, nullable | Rough spread of the matched town |
| `created_at`, `updated_at` | DateTime | |

Indexes: unique `opis_id`; `(latitude, longitude)` for corridor queries; `(state, city)`;
`retail_price`. Database check constraints enforce valid prices (`> 0`, max ≥ min), coordinate
ranges, and that **`unresolved` ⇔ no coordinates**. No unresolved station can ever carry a
point, even if application code is wrong.

### Geolocation strategy

| Option | Verdict |
|--------|---------|
| Nominatim (OSM) | Usage policy caps at 1 request/s and discourages bulk geocoding; exit-style addresses geocode poorly. Rejected for bulk use. |
| US Census Geocoder | Street addresses only; 6 of 6,738 stations have one. Not useful. |
| Commercial APIs (Google, Mapbox) | API keys, cost and terms restricting stored results. Out of scope. |
| **Offline Census Gazetteer (chosen)** | Public domain, no network, deterministic, ~29.5k US places with an internal point and land area. City-level only. |

`geolocate_stations` matches each station's (city, state) to a Census place:

1. Exact normalised name, after removing Census descriptors (`city`, `town`, `CDP`, `(balance)`,
   …; case-sensitive, so *Carson City* stays intact). Normalisation covers `St.`→`Saint`,
   `Ft`→`Fort`, `Mt`→`Mount`, accents, punctuation and hyphens.
2. The same name with spaces removed (`Mc Calla` → `McCalla`).
3. `"<name> City"` (`Boise` → `Boise City`).
4. First segment of consolidated governments (`Indianapolis city (balance)`,
   `Augusta-Richmond County consolidated government (balance)`).

Anything not uniquely matched stays **unresolved**. Two places with the same name in one state
counts as `ambiguous`, and we don't pick one. Lookups are cached per (city, state) during a run,
and results persist on the rows, so later runs only look at unresolved stations.

Writes are grouped by outcome (one `UPDATE … WHERE id IN (…)` per matched place). Measured on
the full dataset, that took the write step from **7.12 s** (Django `bulk_update`, which emits
per-row `CASE` expressions) to **0.85 s**.

### Limitations — read before trusting a coordinate

* **No station has verified coordinates.** City-level points mark the town, not the pump. A
  truck stop at an interstate exit can sit outside the town's limits.
* `location_uncertainty_miles` = radius of a circle with the place's land area (min 1 mile).
  Measured over the 6,228 resolved stations: median 1.6 mi, p90 4.6 mi, p99 12.1 mi, max 15.4 mi
  (Jacksonville, FL). It describes the town's size and is *not* a guaranteed error bound.
* 398 stations (6.0%) are unresolved and are never route candidates. Most are unincorporated
  communities or New England/Mid-Atlantic townships, which the places gazetteer doesn't list.
  Highest counts: VA 40, PA 33, NJ 28, NY 26, MA 21.
* The gazetteer is the 2010 vintage (the newer Census files were unreachable from the build
  environment). Place points rarely move; a newer file can be dropped in without code changes
  (`data/reference/SOURCE.md`).
* **Future enrichment path:** match the CSV's interstate exit numbers (`I-44, EXIT 283`) to
  OpenStreetMap `motorway_junction` nodes from an offline extract, and store the result as
  `geolocation_accuracy="address"`. The schema, source field and "never overwrite address-level"
  rule are already in place.

### Station lookup for route matching

`apps/fuel/queries.py` provides `routable_stations()`, which excludes unresolved stations, and
`stations_in_bounding_box(BoundingBox.around(points, padding_miles))`. Measured: a Chicago–Dallas
box padded by 10 miles returns 1,093 of 6,228 candidates in a median **4.4 ms**, and SQLite uses
the `fuel_station_lat_lng` index. Call `.order_by()` to skip the model's default ordering when
order doesn't matter.

Planned M3 matching (not implemented):

1. Pad the route's bounding box by corridor width + max uncertainty and run one indexed query.
2. In memory, compute each candidate's distance to the route polyline (point-to-segment on a local
   equirectangular projection) and its mile marker along the route.
3. Keep stations within `corridor + location_uncertainty_miles`, and label them approximate in the
   API.

No per-station routing calls are made.

## Routing layer (M2)

### Modules (`apps/routing`)

| Module | Responsibility |
|--------|----------------|
| `serializers.py` | Request shape only: each of `start`/`finish` is `"City, ST"` or `{latitude, longitude}`; ranges, types, blank/format checks. No lookups. |
| `locations.py` | Offline resolution to a `ResolvedLocation` (label, lat, lng, state, source). Raises `LocationError(code, message, details)`. |
| `geography.py` | State codes/names; `UsBoundary` point-in-polygon over the 50 states + DC. |
| `providers.py` | `RoutingProvider` protocol, `OsrmProvider` (one HTTP call, normalised to `Route`), routing error classes with their HTTP status and code. |
| `services.py` | `plan_route()`: resolve both ends → reject identical points → cache lookup → one provider call → cache store. |
| `views.py` | `POST /api/v1/routes/`; maps domain errors to `ApiError`; builds the response. |

The view, service and cache know only `RoutingProvider.route(origin, destination) -> Route`.
Replacing OSRM (Valhalla, GraphHopper, a self-hosted server) means adding one class in
`providers.py` and returning it from `get_routing_provider()`.

### Location resolution

* **City/state** reuses the M1 Census places gazetteer and its matcher (`Gazetteer.lookup`),
  so stations and route endpoints are placed by the same rules. Full state names are accepted.
  A name shared by two places in one state (157 such names in the 2010 file, e.g. *Cottonwood
  city* and *Cottonwood CDP* in AZ) is rejected with the candidates listed; nothing is guessed.
  The only M1 change is additive: `Match` now carries `candidates` for ambiguous matches.
  Spot check: 72 of 73 large US cities resolve; *Honolulu* does not, because the Census calls
  the place *Urban Honolulu CDP* (and Hawaii has no road link to the mainland anyway).
* **Coordinates** must be inside a state or DC polygon from Natural Earth 1:10m (public domain,
  1.1 MB, see `data/reference/SOURCE.md`). This is a real point-in-polygon test (even-odd ray
  casting with per-polygon bounding boxes, pure Python, ~0.1 ms per point), not a bounding box:
  Windsor ON, Nogales (Sonora), Tijuana, the Gulf of Mexico and Puerto Rico are rejected while
  Detroit, Nogales AZ, Key West, Alaska and Hawaii are accepted (all covered by tests).
  **Limitation:** at 1:10m, borders and coasts are generalised by up to roughly 1 km, so points
  within about a kilometre of a coast or international border may be misclassified. A Census
  TIGER/cartographic-boundary file would tighten this; it was not reachable from the build
  environment.
* **Scope:** the 50 states + DC (the fuel data's scope). Canadian provinces and US territories
  get `location_outside_us`. Alaska is accepted; its routes leave the US through Canada.
* Both data files load once per process, at server start (`config/wsgi.py`, `config/asgi.py`):
  ~0.25 s for the gazetteer and ~0.06 s for the polygons. Tests and management commands load
  them lazily.

### Provider: OSRM

Checked on 2026-10-21. The public server `router.project-osrm.org`
([about/usage policy](https://map.project-osrm.org/about.html),
[API usage policy wiki](https://github.com/Project-OSRM/osrm-backend/wiki/API%20Usage%20Policy)):
**at most 1 request per second, no scraping or heavy use, a valid identifying User-Agent, and
attribution** (OSRM + OpenStreetMap/ODbL); no quality or availability guarantee. That fits a
demo; production use needs a self-hosted OSRM or a paid provider (`ROUTING_BASE_URL`).

Request: `GET /route/v1/driving/{lng},{lat};{lng},{lat}?overview=full&geometries=geojson&steps=false&alternatives=false&annotations=false`
— distance (metres), duration (seconds) and the full GeoJSON road geometry in one response.

| Provider outcome | API result |
|------------------|------------|
| `200`, `code: "Ok"`, valid route | `200` |
| `NoRoute`, `NoSegment` (HTTP 400) | `422 route_not_found` |
| timeout (connect ≤ 5 s, read `ROUTING_TIMEOUT`) | `504 routing_timeout` |
| connection error, HTTP 429, HTTP 5xx | `503 routing_unavailable` |
| other 4xx, invalid JSON, missing/invalid distance, duration or geometry | `502 routing_provider_error` |

There are no retries: against a 1 req/s demo server, an immediate retry is more likely to be
rate-limited than to succeed, and it doubles the worst-case latency. The response is validated
strictly (finite, non-negative numbers; a `LineString` of ≥ 2 in-range `[lng, lat]` pairs) and
no route is ever fabricated. One pooled `httpx.Client` per process: creating a client costs
~48 ms (CA bundle load, measured), and keep-alive avoids repeat TLS handshakes.

Distance is converted with the exact international mile (1 mi = 1609.344 m) and rounded to
0.01 mi only in the response; durations are seconds ÷ 60, rounded to 0.1 min.

### Cache

* Backend: Django `DatabaseCache`, table `routefuel_cache` in the same SQLite file, created by the
  `routing.0001_route_cache_table` migration (`createcachetable`, idempotent). No Redis.
  Persists across restarts; `MAX_ENTRIES` 5000 with Django's cull.
* Key: `route:v1:` + SHA-256 of provider name, server URL, profile and both endpoints rounded
  to 5 decimals (~1.1 m). Direction-sensitive (A→B ≠ B→A, one-way roads differ).
* Value: plain dict (distance m, duration s, geometry, provider) — not a pickled class, so
  code changes can't break old entries; an unreadable entry is treated as a miss.
* TTL `ROUTE_CACHE_TTL` (default 7 days): road networks change slowly, and the demo server's
  rate limit makes reuse valuable. Failures are never cached.
* Cache read/write errors (e.g. table missing) are logged and the request continues uncached.
* Not handled: concurrent identical cache misses each call the provider (no request
  coalescing). Acceptable at assessment scale.
* Tests use `LocMemCache`, cleared around every routing test.

### Measured performance (local only)

Measured 2026-10-21 in the build container: Django `runserver` (`DEBUG=false`), SQLite with
the database cache, and a **local stub HTTP server standing in for OSRM** (instant responses,
synthetic straight-line geometry of the stated size). These numbers are RouteFuel's own
overhead; they contain **no real network or OSRM time**. Median of 10 distinct city pairs, via
`curl` on the same machine:

| Geometry points (≈ payload) | Uncached | Cached |
|-----------------------------|---------:|-------:|
| 3 (1 KiB) | 5.5 ms | 2.2 ms |
| 10,000 (226 KiB) | 39.0 ms | 13.1 ms |
| 50,000 (1.1 MiB) | 200.4 ms | 71.6 ms |

Every run made exactly one stub request per uncached route and none for cached ones (11 = 1
warm-up + 10). Reusing one HTTP client cut the small-payload uncached time from 46.6 ms to
4.6 ms; preloading reference data at startup cut the first request after start from ~330 ms to
~70 ms.

Live OSRM could not be called from the build machine or the linked computer (both sit behind
an egress allowlist that blocks the host). It was queried through a separate web fetch tool:
Dallas, TX → Atlanta, GA returned `code: "Ok"`, 1,259,435.7 m (782.58 mi), 50,903.2 s, and a
GeoJSON `LineString` starting `[-96.796754, 32.775944]`; New York → Los Angeles returned
4,496,847.5 m (2,794.21 mi), 179,302.1 s. That confirms the request format and response shape
the client expects, but **the Django client itself has not yet made a live call**, and
real-geometry size and live latency are unmeasured. Large payloads are the main cost; gzip or
a simplified display geometry are M4 options.

## Technical considerations for later milestones

Recorded in M0; item 1 was addressed in M1, the rest are for M2–M4.

1. **Station coordinates.** Done in M1 — see [Fuel data layer](#fuel-data-layer-m1). The API and
   UI must label city-level positions as approximate.
2. **Vehicle model.** 500 mi range ÷ 10 MPG ⇒ 50 gal usable tank.
3. **Inputs to the optimiser.** Remaining fuel, price at each reachable station, and
   reachability (no gap between consecutive usable stations may exceed 500 mi, including the
   first and last legs). If a gap is too large, the API returns a clear "no feasible plan" error.
4. **Greedy is wrong.** Always stopping at the nearest or the cheapest station does not minimise
   cost. The planned algorithm is the standard fixed-route refuelling strategy: at each stop,
   if a cheaper station is reachable within range, buy only enough to reach it; otherwise fill up
   and continue to the cheapest station within range. It runs in O(n log n) for n candidate
   stations and is optimal for a fixed route with linear fuel use.
5. **Starting fuel and expenditure (to confirm in M3).** Proposed defaults: the truck starts with
   an empty tank and buys at a station near the origin; it arrives at the destination with no
   paid-for fuel left. Total expenditure is then the sum of all purchases (≈ route miles ÷ 10 gal
   at the prices paid). Both assumptions will be returned in the response so the number is
   never ambiguous.
6. **One routing call per uncached route.** Done in M2 — see [Routing layer](#routing-layer-m2).
7. **No per-station routing calls.** Off-route distance is a geometric approximation along the
   polyline, which is accurate enough for selecting highway-adjacent stops.
8. **Preprocess once, query cheaply.** Clean and geolocate the CSV at import time; index
   latitude/longitude; keep per-request work to a bounding-box query and in-memory geometry.
