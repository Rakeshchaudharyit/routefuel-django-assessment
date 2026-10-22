# Postman demonstration

Start Django after migrations and station import (see the root README). No authentication or
private API key is needed for the local demo.

## Import and configure

1. In Postman, import `RouteFuel.postman_collection.json` from this directory.
2. Import `RouteFuel.local.postman_environment.json` and select **RouteFuel — local**.
3. Set the environment variable `base_url` to `http://127.0.0.1:8000` without a trailing slash.
   Every request uses `{{base_url}}`; no machine-specific address or credentials are embedded.
4. Send **1. Health check**. Expect 200 and `status: "ok"`.
5. To run the collection, set Collection Runner's delay to **1100 ms** between requests.
   The public routing service is for light use; avoid simultaneous runners or repeated bursts.

Use the desktop app or a local desktop agent so Postman can reach localhost. Do not select a
cloud-only agent for these local requests. Save only public configuration in the environment.

## Requests and expected outcomes

| Request | Expected status | Demonstrates |
|---|---:|---|
| 1. Health check | 200 | API liveness |
| 2. Route — Dallas to Atlanta | 200 | GeoJSON route; cached flag and provider-call count |
| 3. Optimized route — Dallas to Atlanta | 200 | Default 500-mile / 10-MPG fuel plan |
| 4. Optimized route — long distance | 200 | New York–Los Angeles, multiple fuel stops, simplified geometry |
| 5. Optimized route — custom vehicle and starting fuel | 200 | Vehicle overrides, starting-fuel valuation, practical stop policy |
| 6. Invalid input | 400 | Field-level validation |
| 7a. Unreachable route — Los Angeles to Honolulu | 422 | `route_not_found` |
| 7b. Infeasible fuel plan — 10-mile range | 422 | `no_feasible_fuel_plan` |

The collection has eight requests. Each includes Postman JavaScript assertions; inspect their
results in Postman. Error cases are expected successes of the demonstration, not server faults.
Exact station choices and timings depend on the route provider and local data.

## A short recording sequence

Have the collection and response panels ready before recording. Send health, standard route,
then invalid input. In the optimized Dallas request, show the summary and one stop, not the
entire geometry array. Send the long route and show ordered stops and purchase cost. If time
permits, show the custom-vehicle summary. Show the unreachable and infeasible cases in the
collection's passing results; do not wait through repeated network calls during the video.

Expected audited examples: Dallas–Atlanta 778.8 miles / three stops / $78.19 purchases;
New York–Los Angeles 2,810.37 miles / 17 stops / $698.65 purchases. Neither purchase total
includes unknown-price starting fuel. The custom request does supply a starting price.

Repeat a successful request to show `meta.cached: true` and `meta.routing_requests: 0`.
For an explicit fresh-versus-cached check before recording, run from `backend/` with the
virtual environment active:

```bash
python manage.py verify_routing
```

This makes actual external calls, clears the Dallas route cache entry and checks fresh/cache
behavior. If the provider fails, keep the error visible and describe the dependency; do not
present old results as a new live success.

## Terminal alternative

From the repository root, with Django running:

```bash
python docs/postman/run_collection.py --base-url http://127.0.0.1:8000
```

The standard-library runner waits 1.1 seconds between requests and checks the eight HTTP
statuses. It does **not** execute Postman's JavaScript assertions. M8 ran it against real
Django and OSRM: 8/8 expected statuses passed. Native Postman/Newman assertions still need
manual execution before submission; this report does not claim they ran in the terminal.
