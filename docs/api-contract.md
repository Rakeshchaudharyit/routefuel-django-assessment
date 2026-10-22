# RouteFuel API contract (v1)

For the M5/M6 dashboard. Every field below exists in the current implementation and is
covered by `backend/tests/test_api_integration.py::test_optimize_response_schema`.

## Base URL and transport

| | |
|---|---|
| Local base URL | `http://127.0.0.1:8000` (`python manage.py runserver`) |
| Prefix | `/api/v1/` |
| Format | JSON in and out; send `Content-Type: application/json` |
| Auth | None |
| CORS | Origins in `DJANGO_CORS_ALLOWED_ORIGINS` (default `http://localhost:3000,http://127.0.0.1:3000`), paths `/api/*` only |

Read the base URL from an environment variable in the frontend (e.g. `NEXT_PUBLIC_API_BASE_URL`).

## Endpoints

| Method | Path | Use |
|---|---|---|
| GET | `/api/v1/health/` | Liveness: `{"status": "ok", "service": "routefuel-api"}` |
| POST | `/api/v1/routes/` | Route only (no fuel plan) |
| POST | `/api/v1/routes/optimize/` | Route + fuel plan — **the dashboard endpoint** |

Other methods on these paths return `405 method_not_allowed`.

## `POST /api/v1/routes/optimize/` — request

```jsonc
{
  "start": "Dallas, TX",                       // required: "City, ST" | "City, State" | {latitude, longitude}
  "finish": {"latitude": 33.749, "longitude": -84.388},   // required, same forms
  "vehicle": {                                 // optional; every field optional
    "range_miles": 500,                        // number, > 0 and <= 5000; default 500
    "mpg": 10,                                 // number, > 0 and <= 200; default 10
    "starting_fuel_gallons": 50,               // number, 0..range_miles/mpg; default = full tank
    "starting_fuel_price_per_gallon": "3.199"  // string or number, 0.50..20.00, <= 8 dp; default none
  },
  "stop_policy": {"min_savings_per_stop": "2.00"},  // optional; see "Practical stops"
  "geometry_detail": "full"                    // optional: "full" (default) | "simplified"
}
```

* Numbers must be JSON numbers (`"10"` for `mpg` is rejected); booleans are rejected.
* City inputs resolve offline to the Census point of the place. A name shared by two places
  in one state is rejected with candidates (send coordinates instead).
* Coordinates must lie inside one of the 50 states or DC.

## Response (200)

Real response for `{"start": "Dallas, TX", "finish": "Atlanta, GA"}` with default vehicle
settings, recorded live against OSRM on 22 October 2026. Only the geometry coordinates are
shortened (the full line has 8,177 points). Results change if provider data changes.

```json
{
  "origin": {"label": "Dallas, TX", "latitude": 32.794176, "longitude": -96.765503, "state": "TX", "source": "census_place"},
  "destination": {"label": "Atlanta, GA", "latitude": 33.762909, "longitude": -84.422675, "state": "GA", "source": "census_place"},
  "route": {
    "distance_miles": 778.8,
    "duration_minutes": 843.9,
    "geometry": {"type": "LineString", "coordinates": [[-96.765226, 32.793945], [-96.765446, 32.793758], "... 8,175 more [lon, lat] pairs"]},
    "geometry_detail": "full",
    "geometry_tolerance_meters": null
  },
  "vehicle": {"range_miles": 500, "mpg": 10, "tank_capacity_gallons": "50.000",
              "starting_fuel_gallons": "50.000", "starting_fuel_price_per_gallon": null},
  "fuel_plan": {
    "currency": "USD",
    "stops": [
      {"sequence": 1,
       "station": {"opis_id": 60540, "name": "CIRCLE K #2706340", "address": "I-20, EXIT 533", "city": "Canton", "state": "TX",
                   "latitude": 32.554245, "longitude": -95.863534},
       "location": {"accuracy": "city", "source": "census_gazetteer_places_2010", "approximate": true,
                    "uncertainty_miles": 1.4, "distance_from_route_miles": 1.71},
       "route_mile": 57.2, "price_per_gallon": "2.77566666", "gallons": "5.718", "cost": "15.87",
       "fuel_on_arrival_gallons": "44.282", "fuel_on_departure_gallons": "50.000"},
      {"sequence": 2,
       "station": {"opis_id": 4463, "name": "QUIKTRIP #7901", "address": "I-20, EXIT 556 & US-69", "city": "Lindale", "state": "TX",
                   "latitude": 32.493887, "longitude": -95.407275},
       "location": {"accuracy": "city", "source": "census_gazetteer_places_2010", "approximate": true,
                    "uncertainty_miles": 1.4, "distance_from_route_miles": 1.77},
       "route_mile": 84.5, "price_per_gallon": "2.80733333", "gallons": "2.731", "cost": "7.67",
       "fuel_on_arrival_gallons": "47.269", "fuel_on_departure_gallons": "50.000"},
      {"sequence": 3,
       "station": {"opis_id": 64558, "name": "MR FUEL #1203", "address": "I-20, EXIT 129", "city": "Meridian", "state": "MS",
                   "latitude": 32.384191, "longitude": -88.68944},
       "location": {"accuracy": "city", "source": "census_gazetteer_places_2010", "approximate": true,
                    "uncertainty_miles": 4.1, "distance_from_route_miles": 1.52},
       "route_mile": 492.5, "price_per_gallon": "2.81233333", "gallons": "19.431", "cost": "54.65",
       "fuel_on_arrival_gallons": "9.202", "fuel_on_departure_gallons": "28.633"}
    ],
    "summary": {
      "number_of_stops": 3,
      "total_gallons_consumed": "77.880",
      "starting_fuel_used_gallons": "50.000",
      "total_gallons_purchased": "27.880",
      "total_purchase_cost": "78.19",
      "fuel_remaining_at_destination_gallons": "0.000",
      "starting_fuel_value": null,
      "estimated_total_fuel_cost": null,
      "estimated_total_fuel_cost_status": "unavailable",
      "cost_note": "Whole-trip fuel cost is unavailable: 50.000 gal of starting fuel were used and starting_fuel_price_per_gallon was not provided. total_purchase_cost covers only fuel bought at the recommended stops."
    },
    "stop_policy": null,
    "candidates": {"corridor_miles": 5, "stations_in_search_area": 240, "stations_on_route": 126}
  },
  "meta": {"provider": "osrm", "attribution": "Routing © OSRM; map data © OpenStreetMap contributors (ODbL)",
           "cached": false, "routing_requests": 1,
           "timings_ms": {"route": 947.43, "station_matching": 19.79, "optimization": 0.33}}
}
```

With `"vehicle": {"starting_fuel_price_per_gallon": "3.00"}`, the same route returns
`"starting_fuel_value": "150.00"`, `"estimated_total_fuel_cost": "228.19"` and
`"estimated_total_fuel_cost_status": "calculated"`. With `"starting_fuel_gallons": 0`, it
buys all 77.881 gallons at 5 stops for `"total_purchase_cost": "217.37"`.

### Other endpoints

`GET /api/v1/health/` → `200 {"status": "ok", "service": "routefuel-api"}`. It does not check the
database or the provider.

`POST /api/v1/routes/` with `{"start": "Dallas, TX", "finish": "Atlanta, GA"}` → `200` with
`origin`, `destination`, `route` (same shape as above) and `meta` without `timings_ms`:

```json
{"meta": {"provider": "osrm", "attribution": "Routing © OSRM; map data © OpenStreetMap contributors (ODbL)",
          "cached": true, "routing_requests": 0}}
```

### TypeScript shape

```ts
type Decimal = string;  // money "78.41" (2 dp), gallons "27.880" (3 dp), price "2.81233333" (>= 3 dp)

interface ResolvedLocation {
  label: string; latitude: number; longitude: number;
  state: string;                                  // USPS code
  source: "census_place" | "coordinates";
}

interface FuelStop {
  sequence: number;                               // 1-based, in driving order
  station: { opis_id: number; name: string; address: string; city: string; state: string;
             latitude: number; longitude: number }; // town-level point, NOT the pump
  location: {
    accuracy: "city" | "address";                 // all current data: "city"
    source: string;                               // "census_gazetteer_places_2010"
    approximate: boolean;                         // true unless accuracy === "address"
    uncertainty_miles: number | null;             // rough radius of the town
    distance_from_route_miles: number;            // straight line, town point to route
  };
  route_mile: number;                             // miles from origin along the route (0.1)
  price_per_gallon: Decimal;
  gallons: Decimal;                               // bought at this stop
  cost: Decimal;                                  // price_per_gallon x gallons, to the cent
  fuel_on_arrival_gallons: Decimal;
  fuel_on_departure_gallons: Decimal;
}

interface OptimizeResponse {
  origin: ResolvedLocation;
  destination: ResolvedLocation;
  route: {
    distance_miles: number;                       // provider driving distance
    duration_minutes: number;                     // provider driving time, no fuel stops
    geometry: { type: "LineString"; coordinates: [number, number][] };  // [lon, lat]
    geometry_detail: "full" | "simplified";
    geometry_tolerance_meters: number | null;     // 25 when simplified
  };
  vehicle: { range_miles: number; mpg: number; tank_capacity_gallons: Decimal;
             starting_fuel_gallons: Decimal; starting_fuel_price_per_gallon: Decimal | null };
  fuel_plan: {
    currency: "USD";
    stops: FuelStop[];                            // [] when the starting fuel covers the trip
    summary: {
      number_of_stops: number;
      total_gallons_consumed: Decimal;            // distance / mpg
      starting_fuel_used_gallons: Decimal;
      total_gallons_purchased: Decimal;           // sum of stop gallons
      total_purchase_cost: Decimal;               // sum of stop costs = money spent at stops
      fuel_remaining_at_destination_gallons: Decimal;
      starting_fuel_value: Decimal | null;
      estimated_total_fuel_cost: Decimal | null;  // whole-trip fuel cost
      estimated_total_fuel_cost_status: "calculated" | "unavailable";
      cost_note: string;                          // one sentence explaining the totals
    };
    stop_policy: null | { min_savings_per_stop: Decimal; stops_removed: number;
      removed_station_opis_ids: number[]; minimum_purchase_cost: Decimal;
      minimum_cost_number_of_stops: number; extra_cost: Decimal };
    candidates: { corridor_miles: number; stations_in_search_area: number; stations_on_route: number };
  };
  meta: { provider: string; attribution: string; cached: boolean; routing_requests: 0 | 1;
          timings_ms: { route: number; station_matching: number; optimization: number } };
}
```

`POST /api/v1/routes/` returns `origin`, `destination`, `route` (same shape) and `meta`
without `timings_ms`. It accepts `start`, `finish` and `geometry_detail`.

## Display rules for the dashboard

* **Map line:** `route.geometry` is GeoJSON `[longitude, latitude]` — pass it to a MapLibre
  `geojson` source as-is. Request `geometry_detail: "simplified"` for drawing; full routes
  can exceed 1 MB (40–50k points coast to coast). Stops and totals are identical either way.
* **Stop markers:** use `station.latitude/longitude`, but they mark the **town**, not the
  truck stop. Show them as approximate (e.g. a ring sized by `uncertainty_miles`) whenever
  `location.approximate` is true, and label positions as approximate.
* **Money:** keep the strings; don't round-trip them through floats. `total_purchase_cost`
  equals the sum of the stop `cost` values.
* **Whole-trip cost:** show `estimated_total_fuel_cost` only when its status is
  `"calculated"`; otherwise show `cost_note`. Never present `total_purchase_cost` alone as the
  cost of all fuel burnt when starting fuel was used.
* **Attribution:** display `meta.attribution` on the map (required by the OSRM/OSM terms).
* **Duration** excludes refuelling time.

## Practical stops

`stop_policy.min_savings_per_stop` (USD, > 0, ≤ 1000, ≤ 2 dp) asks the API to drop stops that
save less than that amount, one at a time, re-optimising each time. The response then shows the
practical plan, and `fuel_plan.stop_policy` reports the minimum-cost alternative and the extra
cost. It is a greedy rule, not an exact "fuel + per-stop cost" optimum. Without it,
`stop_policy` is `null` and the plan is the minimum-purchase-cost plan.

Gallons are display-rounded to 0.001 per stop; replay validation uses raw quantities. The sum
of displayed purchases can differ slightly from consumed minus starting fuel (0.002 gal in
the M7 17-stop example). Positive tiny purchases can display as `0.000` gallons. The default
objective minimizes continuous purchase cost, not the sum after line-by-line cent rounding.
`extra_cost` is a signed decimal string: effectively equal exact-cost plans can produce
`"-0.01"` after different per-stop rounding. Purchase costs and prices remain nonnegative.
Range and MPG must also derive a finite, positive capacity; overflow/underflow returns 400.

## Errors

Every error uses one envelope:

```json
{"error": {"code": "ambiguous_location", "message": "Human-readable sentence.", "details": {}}}
```

| Status | `code` | When | `details` |
|---|---|---|---|
| 400 | `invalid` | Missing/invalid `start`, `finish`, `vehicle`, `stop_policy`, `geometry_detail` | Field errors, e.g. `{"vehicle": {"mpg": ["..."]}}` |
| 400 | `parse_error` | Body is not valid JSON | `null` |
| 415 | `unsupported_media_type` | Not `application/json` | `null` |
| 405 | `method_not_allowed` | Not POST | `null` |
| 422 | `location_not_found` | Unknown state, or no Census place by that name | `{"field": "start", "city", "state"}` |
| 422 | `ambiguous_location` | Name shared by several places in the state | `{"field", "city", "state", "candidates": [{name, latitude, longitude}]}` |
| 422 | `location_outside_us` | Coordinates outside the 50 states + DC; Canadian province; US territory | `{"field", ...}` |
| 422 | `same_location` | Start and finish are the same point | `null` |
| 422 | `route_not_found` | No drivable route (e.g. to Hawaii) | `null` |
| 422 | `no_feasible_fuel_plan` | A stretch is longer than the vehicle's reach | `{"from_mile", "to_mile", "gap_miles", "max_reach_miles"}` |
| 502 | `routing_provider_error` | Provider rejected the request or sent invalid data | `null` |
| 503 | `routing_unavailable` | Provider unreachable, rate-limited (429) or failing (5xx) | `null` |
| 504 | `routing_timeout` | No provider answer within `ROUTING_TIMEOUT` (default 10 s) | `null` |
| 500 | `internal_error` | Unexpected server error (logged; no internals in the response) | `null` |

`details.field` on location errors names the input to highlight (`start` is checked first).

## Caching, attribution and timing

* Successful routes are cached in the database for `ROUTE_CACHE_TTL` (default 7 days), keyed
  by provider and by origin and destination rounded to about 1 m. The key is
  direction-sensitive. Errors are not cached.
* `meta.routing_requests` is `1` for a fresh route and `0` for a cached one. No routing request
  is made per station. Identical concurrent requests for an uncached route share one provider
  call.
* `meta.attribution` must be shown with the map (OSRM/OpenStreetMap terms).

Measured live on 22 October 2026 through the local Django server (single observations, not
guarantees):

| Request | Client total | OSRM part | Local processing |
|---|---|---|---|
| Dallas → Atlanta, uncached | 984 ms | 947 ms | ~20 ms station matching, 0.3 ms optimization |
| Dallas → Atlanta, cached | 28 ms | — | — |
| New York → Los Angeles, uncached | 3,590 ms | 3,539 ms | 29 ms matching, 0.6 ms optimization |
| Dallas → Austin, uncached | 374 ms | 351 ms | ~14 ms |

* Show a loading state immediately; uncached long routes can take several seconds on the public
  OSRM server, which allows about 1 request per second.
* Set the client timeout to at least 15 s. The server's provider timeout is 10 s, after which
  the API answers `504 routing_timeout` itself.
