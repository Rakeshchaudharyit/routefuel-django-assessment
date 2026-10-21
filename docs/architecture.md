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

### Request flow (steps 1–3 built in M2, 4–6 in M3)

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

## Fuel-stop optimisation (M3)

`POST /api/v1/routes/optimize/` = M2 route (same cache, same single provider call) → stations
near the route (one indexed query + local geometry) → optimiser → replay check → response.

| Module | Responsibility |
|--------|----------------|
| `optimization/geometry.py` | `RouteLine`: cumulative haversine distance, thinned matching line, grid index, `locate()` → route mile + offset. Pure Python. |
| `optimization/optimizer.py` | `Vehicle`, `Candidate`, `optimize()`, `check_plan()`, `InfeasiblePlan`. Pure Python. |
| `routing/fuel_plans.py` | Orchestration: route, station query, placement, optimiser, response money/rounding. |
| `routing/serializers.py`, `views.py` | `vehicle` validation; `OptimizeRouteView`; shared error mapping (`no_feasible_fuel_plan`). |

### Model and assumptions

| Item | Value / rule |
|------|--------------|
| Range, efficiency | 500 mi, 10 MPG (request-configurable) |
| Tank capacity | `range_miles / mpg` = 50 gal |
| Consumption | Linear: `miles / mpg` gallons for any stretch |
| Starting fuel | Default **full tank (50 gal)**, configurable 0 – capacity. Already paid for. |
| Objective | Minimise money spent at stations. Fuel left at the destination has no value in the objective. |
| Purchases | Any positive quantity at any candidate station, up to the free tank space |
| Station position | Its projected route mile; detour to/from the station is not modelled |
| Price | `FuelStation.retail_price` (lowest listed price for that OPIS ID, exact `Decimal`) |

Consequences, reported separately in `fuel_plan.summary`:

1. `total_gallons_consumed` = distance ÷ mpg.
2. `starting_fuel_used_gallons` = min(starting fuel, consumed) — starting fuel is burnt first
   because it costs nothing more to use it.
3. `total_gallons_purchased` = consumed − starting fuel used (the optimiser never buys fuel it
   does not need, so nothing paid-for is left at the destination).
4. `total_purchase_cost` = Σ stop costs. Each stop: `price × gallons` (gallons rounded to
   0.001), rounded half-up to the cent.
5. `fuel_remaining_at_destination_gallons` = starting fuel − starting fuel used.
6. `starting_fuel_value` = starting fuel used × `starting_fuel_price_per_gallon`, and
   `estimated_total_fuel_cost` = (4) + that — **only when the client supplies the price**.
   Otherwise both are `null`: the starting tank has real value, but its price is unknown, and
   no price is invented.

With the default full tank, `total_purchase_cost` is *not* the cost of all fuel burnt on the
trip — the first 50 gallons came from the tank. Clients wanting "fuel cost of the trip" should
pass a starting price, or `starting_fuel_gallons: 0` (then every gallon is bought on the route
and purchase cost = trip fuel cost; requires a station at the origin).

### Algorithm: fill up, refund later

Stations are sorted by route mile (then price, then OPIS ID). The tank is a FIFO queue of
*lots* (price, gallons); the starting fuel is the first lot.

1. Drive to the next station, burning the oldest lots first.
2. At a station selling at `p`, remove every lot still in the tank that cost more than `p`
   (it is treated as never bought), then top up to capacity with fuel at `p`.
3. At the destination, unburnt purchased lots are removed the same way.

A station's purchase is the part of its lot that was actually burnt. Because step 2 always
removes the dearest fuel, the queue stays sorted from cheapest (oldest) to dearest (newest).
Unrolled, this is the classical rule for a fixed route: at a station, if a cheaper station is
within one tank's range, buy only enough to reach the first such station; otherwise fill the
tank (and burn this fuel until something cheaper appears). That rule is optimal for a fixed
path with linear consumption and one tank capacity (Khuller, Malekian & Mestre, *To fill or not
to fill: the gas station problem*, ACM Trans. Algorithms 7(3), 2011). Runtime is O(n log n)
for the sort plus O(n) for the pass; measured < 1 ms for 260 candidates.

**Feasibility.** On leaving any station the notional tank is full, so the procedure fails only
where *no* plan can succeed: the starting fuel cannot reach the first station/destination, or
two consecutive stations (or the last station and the destination) are more than one range
apart. That gap is returned as `no_feasible_fuel_plan` with its miles. A partial plan is never
returned.

**Why not simpler rules.** "Nearest station", "cheapest station in range, fill up" and "fill up
whenever below X" are all suboptimal; `test_cheapest_next_station_is_not_globally_optimal` is a
concrete counter-example (filling up at the cheapest reachable station costs $250.00; the
optimum is $247.00). A DP/shortest-path formulation over discretised fuel levels would also be
exact but costs O(n · levels²) and needs a discretisation choice; the greedy is exact for the
continuous model.

**Verification.**

* `tests/reference_optimizer.py` is an independent dynamic program over whole-gallon fuel
  levels. For instances whose legs burn whole gallons it is exact: the problem is an LP with an
  interval (consecutive-ones) constraint matrix, which is totally unimodular, so an integral
  optimum exists. The optimiser matches it on 10,000 random instances (`range(20)` seeds × 500,
  including infeasible ones and repeated prices) and on 1,000 truck-like instances with
  fractional gallons (tenth-gallon units).
* `check_plan()` replays every plan before it is returned: stops in route order, tank never
  below 0 or above capacity, purchases positive, fuel balance closes. A failure raises an
  internal error (HTTP 500) rather than returning the plan.
* Hand-worked cases cover routes < 500, = 500, 500–1,000 and > 1,000 miles, equal prices,
  dear-then-cheap and cheap-then-dear, duplicates at one location, 8-decimal prices, every
  starting-fuel case, unreachable gaps and stations near the destination.

**Ties and small purchases.** Equal prices: the earlier station's fuel is used first and
nothing is swapped, so results are deterministic. The objective is purely cost, so the plan can
include a small top-up when it saves money (the Dallas–Atlanta example buys 5.7 gal at a station
2–4 cents cheaper than later ones). A per-stop cost or minimum purchase would change the model
and is not applied.

### Candidate stations

1. **Prefilter (one SQL query).** The route is cut into ~200-mile pieces; each piece's bounding
   box is padded by `FUEL_CORRIDOR_MILES` + the largest `location_uncertainty_miles` in the
   table (one aggregate query), and the boxes are OR-ed into one indexed query on
   `(latitude, longitude)`. Unresolved stations (no coordinates) are excluded by
   `routable_stations()`. Measured: ~740 rows for New York → Los Angeles instead of ~6,000.
2. **Placement (in memory).** Each station's point is projected onto the route (`RouteLine.locate`)
   and kept if its straight-line offset ≤ `FUEL_CORRIDOR_MILES` (5) **+ its own
   `location_uncertainty_miles`** (median 1.6, max 15.4). Stations sharing a town point are
   located once. The station's route mile is the projected point's distance along the line.
3. Price, range and remaining fuel are then handled by the optimiser.

The 5-mile base corridor reflects that city-level points mark the town centre while truck stops
sit at nearby interstate exits. It is a configurable assumption, not a measured detour.

**Mile markers.** Distances along the polyline use the haversine formula (mean Earth radius
3,958.76 mi), never raw degree differences. The polyline is a chain of straight segments, so
its length differs from the provider's road distance; every mile marker is multiplied by
`provider distance / polyline length`, so the destination is exactly at the provider's
distance and stop spacing is consistent with the fuel burnt. For matching, the line is thinned
to vertices ≥ 0.5 mi apart (each keeps its distance along the full line); on highway curves the
thinned chord stays within ~0.1 mi of the road. A grid index (0.25° cells) limits each lookup to
nearby segments. The offset uses a local equirectangular projection around the station
(accurate to well under 1% within the ≤ 20-mile search radius).

### Approximate coordinates — what the response does and does not claim

* Every stop carries `location.accuracy` (`city` for all current data), `source`,
  `uncertainty_miles` and `approximate: true` unless accuracy is `address`.
* `latitude`/`longitude` are the **town's** Census point, not the station.
* `distance_from_route_miles` is town-point-to-route, straight line. Real access distance,
  exit position and detour fuel are **not** validated; mile markers can be off by up to the
  uncertainty radius.
* 398 stations without coordinates can never be recommended.

### Performance (measured locally, 2026-10-21)

Real SQLite station DB (6,228 routable stations) and DB route cache; **OSRM replaced by a local
stand-in serving synthetic geometries** (straight segments through Census points of towns along
the interstate, densified to OSRM-like spacing). No real network time is included.

In-process, median of 10 runs of `plan_route_with_fuel` (default truck, full start), at two
geometry densities (OSRM's full overview is typically the denser one):

| Stand-in route | Points | Candidates (area → on route) | Matching | Optimiser | Total uncached / route cached |
|---|---:|---|---:|---:|---:|
| Dallas → Atlanta (I-20), 778.8 mi | 2,505 | 242 → 111 | 10.3 ms | 0.29 ms | 13.2 / 12.6 ms |
| | 12,534 | 242 → 111 | 17.7 ms | 0.35 ms | 24.1 / 21.5 ms |
| New York → Los Angeles, 2,794.2 mi | 8,482 | 743 → 261 | 30.5 ms | 0.65 ms | 37.0 / 32.8 ms |
| | 42,439 | 744 → 261 | 72.6 ms | 0.79 ms | 95.9 / 86.2 ms |
| Seattle → Miami, 3,100.4 mi | 10,123 | 728 → 215 | 31.7 ms | 0.54 ms | 38.1 / 36.1 ms |
| | 50,648 | 731 → 215 | 64.5 ms | 0.56 ms | 89.2 / 83.4 ms |

Plans: Dallas → Atlanta 2 stops, 27.880 gal, $78.20; New York → Los Angeles 12 stops,
229.421 gal, $683.17; Seattle → Miami 14 stops, ~260.04 gal, ~$807.5 (the last digit moves with
geometry density because mile markers shift by fractions of a mile). "Matching" = building the
route index + station query + placement.

Over HTTP (`runserver`, `DEBUG=false`, curl, median of 7, stand-in route served over local HTTP):

| Route (points, payload) | Uncached | Cached route |
|---|---:|---:|
| Dallas → Atlanta (12,534 pts, 281 KiB) | 66.2 ms | 46.1 ms |
| New York → Los Angeles (42,439 pts, 968 KiB) | 203.2 ms | 142.2 ms |

Each run made exactly one provider request per uncached route and none when cached (8 stand-in
requests for 16 API calls). Database work per request: one uncertainty aggregate, one station
query, plus the cache read (and write on a miss). The remaining cost is mostly parsing,
caching and serialising the full-resolution geometry — an M4 item (simplified display geometry,
gzip).

### Known limitations

* Live OSRM has not been called from Django (egress blocked here); all M3 results above use
  mocked or stand-in routes.
* Station positions are town-level; detours and exit access are not modelled.
* Prices are a static snapshot (lowest listed per OPIS ID); no time or availability data.
* If a route passes a town twice, the station is placed at the closer pass only.
* Starting-fuel value is reported only when a price is supplied.
* No per-stop penalty: the plan may include small cost-saving top-ups.

## Technical considerations for later milestones

Recorded in M0; items 1–7 are now addressed, item 8 remains guidance.

1. **Station coordinates.** Done in M1 — see [Fuel data layer](#fuel-data-layer-m1). The API and
   UI must label city-level positions as approximate.
2. **Vehicle model.** 500 mi range ÷ 10 MPG ⇒ 50 gal usable tank.
3. **Inputs to the optimiser.** Done in M3. Remaining fuel, price at each reachable station, and
   reachability (no gap between consecutive usable stations may exceed 500 mi, including the
   first and last legs). If a gap is too large, the API returns a clear "no feasible plan" error.
4. **Greedy is wrong.** Done in M3 (fill up, refund later). Always stopping at the nearest or the cheapest station does not minimise
   cost. The planned algorithm is the standard fixed-route refuelling strategy: at each stop,
   if a cheaper station is reachable within range, buy only enough to reach it; otherwise fill up
   and continue to the cheapest station within range. It runs in O(n log n) for n candidate
   stations and is optimal for a fixed route with linear fuel use.
5. **Starting fuel and expenditure.** Decided in M3: start with a full tank (configurable),
   report purchases and starting-fuel use separately, value the starting fuel only when a price
   is supplied. See [Model and assumptions](#model-and-assumptions).
6. **One routing call per uncached route.** Done in M2 — see [Routing layer](#routing-layer-m2).
7. **No per-station routing calls.** Done in M3. Off-route distance is a geometric approximation along the
   polyline, which is accurate enough for selecting highway-adjacent stops.
8. **Preprocess once, query cheaply.** Clean and geolocate the CSV at import time; index
   latitude/longitude; keep per-request work to a bounding-box query and in-memory geometry.
