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

Abridged real response (stand-in route geometry; see README):

```json
{
  "origin": {"label": "Dallas, TX", "latitude": 32.794176, "longitude": -96.765503, "state": "TX", "source": "census_place"},
  "destination": {"label": "Atlanta, GA", "latitude": 33.762909, "longitude": -84.422675, "state": "GA", "source": "census_place"},
  "route": {
    "distance_miles": 778.8,
    "duration_minutes": 779.5,
    "geometry": {"type": "LineString", "coordinates": [[-96.765503, 32.794176], [-95.304631, 32.314954], [-84.422675, 33.762909]]},
    "geometry_detail": "simplified",
    "geometry_tolerance_meters": 25.0
  },
  "vehicle": {"range_miles": 500.0, "mpg": 10.0, "tank_capacity_gallons": "50.000",
              "starting_fuel_gallons": "50.000", "starting_fuel_price_per_gallon": "3.199"},
  "fuel_plan": {
    "currency": "USD",
    "stops": [{
      "sequence": 1,
      "station": {"opis_id": 64558, "name": "MR FUEL #1203", "address": "I-20, EXIT 129",
                  "city": "Meridian", "state": "MS", "latitude": 32.384191, "longitude": -88.68944},
      "location": {"accuracy": "city", "source": "census_gazetteer_places_2010", "approximate": true,
                   "uncertainty_miles": 4.1, "distance_from_route_miles": 0.07},
      "route_mile": 496.3,
      "price_per_gallon": "2.81233333",
      "gallons": "27.880",
      "cost": "78.41",
      "fuel_on_arrival_gallons": "0.370",
      "fuel_on_departure_gallons": "28.250"
    }],
    "summary": {
      "number_of_stops": 1,
      "total_gallons_consumed": "77.880",
      "starting_fuel_used_gallons": "50.000",
      "total_gallons_purchased": "27.880",
      "total_purchase_cost": "78.41",
      "fuel_remaining_at_destination_gallons": "0.000",
      "starting_fuel_value": "159.95",
      "estimated_total_fuel_cost": "238.36",
      "estimated_total_fuel_cost_status": "calculated",
      "cost_note": "Purchases ($78.41) plus 50.000 gal of starting fuel valued at $3.199/gal."
    },
    "stop_policy": {"min_savings_per_stop": "1.00", "stops_removed": 1, "removed_station_opis_ids": [60540],
                    "minimum_purchase_cost": "78.20", "minimum_cost_number_of_stops": 2, "extra_cost": "0.21"},
    "candidates": {"corridor_miles": 5.0, "stations_in_search_area": 242, "stations_on_route": 111}
  },
  "meta": {"provider": "osrm", "attribution": "Routing © OSRM; map data © OpenStreetMap contributors (ODbL)",
           "cached": true, "routing_requests": 0,
           "timings_ms": {"route": 1.95, "station_matching": 7.11, "optimization": 7.13}}
}
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

## Loading and timeouts

| Situation | Typical server time (measured locally, stand-in provider) |
|---|---|
| Route already cached | ~7–15 ms (Dallas–Atlanta to coast to coast) |
| New route | provider time + ~45–115 ms processing |
| Public OSRM provider time | not measured from Django (blocked in the build environment); expect hundreds of ms to a few seconds |

* Show a loading state immediately; a new route can take a few seconds on the public OSRM
  server, and it allows only 1 request/second — debounce requests.
* Set the client timeout to at least 15 s (server provider timeout is 10 s; the API answers
  `504 routing_timeout` itself).
* Identical concurrent requests are coalesced server-side (one provider call), so a retry
  while the first request is still running is cheap.
* `meta.cached` tells you whether the route came from the cache.
