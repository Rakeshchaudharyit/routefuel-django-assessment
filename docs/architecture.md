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
  ├── fuel          CSV import, FuelStation data, corridor queries
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

### Request flow (target for M2–M4)

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

`details` carries field-level validation errors when present. Routing-provider failures
(M2) will map to explicit codes (e.g. `route_not_found`, `routing_unavailable`) rather than
leaking provider responses.

## Technical considerations for later milestones

These are recorded now and deliberately **not** implemented in M0.

1. **Station coordinates.** The CSV may only contain address/city/state. We must not fabricate
   exact station positions. Plan: approximate each station from an offline US city dataset,
   store a precision flag, and surface "approximate location" in the API and UI.
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
6. **One routing call per uncached route.** Cache by rounded start/finish coordinates.
7. **No per-station routing calls.** Off-route distance is a geometric approximation along the
   polyline, which is accurate enough for selecting highway-adjacent stops.
8. **Preprocess once, query cheaply.** Clean and geolocate the CSV at import time; index
   latitude/longitude; keep per-request work to a bounding-box query and in-memory geometry.
