# Loom demo script — target 4:50

Record manually after reviewing the repository. Target 4:50; stop before 5:00. The spoken
text below is deliberately brief so the API requests and screen changes fit the timing.
Rehearse once and trim pauses rather than speeding through the explanation.

## Before recording (outside the five minutes)

- Start Django with imported stations and Next.js; use `http://localhost:3000`.
- Import the Postman collection/environment and set `base_url`. Set Runner delay to 1100 ms.
- Run `verify_routing` and the collection. Warm Dallas–Atlanta and New York–Los Angeles for
  reliable switching; identify cached responses honestly during the recording.
- Open Postman, the dashboard, `backend/config/urls.py`, the four `backend/apps/` folders and
  `backend/apps/optimization/optimizer.py`. Keep README and the QA report available.
- Leave the dashboard on Dallas–Atlanta, default 500-mile range, 10 MPG, 50 gallons starting
  fuel, blank starting price and blank practical-stop threshold.
- Close `.env`, personal tabs, notifications and terminals containing credentials. Show the
  app, requests and source code; no secret values are needed.
- Check that route totals still match the current provider. Use current results if they change.
  Do not call cached data a fresh routing request or claim exact station positions.

## 0:00–0:30 — Introduction

**Screen:** README overview, then Postman collection.

**Say:**

> “This is RouteFuel, my implementation of the Spotter AI Django assessment. It accepts two
> US locations, gets a driving route, and recommends fuel purchases using the supplied price
> dataset. The default vehicle has a 500-mile range at ten miles per gallon. I’ll show the API,
> the map, and the reasoning behind the optimizer.”

## 0:30–1:30 — Django API in Postman

**Actions:** Send health; send standard Dallas–Atlanta route; collapse geometry and show metadata.
Send invalid input and show field errors. Briefly point to the collection's custom-vehicle,
unreachable and infeasible cases and passing results from the preflight run.

**Say:**

> “There are three endpoints: health, routing, and fuel optimization. Locations accept city
> and state names or coordinates. The route response contains distance, duration and GeoJSON.
> This request is cached, so the routing-request count is zero. A fresh successful route makes
> one provider call. Invalid input gets a structured 400 response; undrivable routes and
> infeasible fuel plans have distinct 422 errors.”

## 1:30–2:20 — Dallas to Atlanta

**Actions:** Send the default optimized Dallas request. Expand `fuel_plan.summary`, then one
stop. Keep the complete route array collapsed.

**Say:**

> “Dallas to Atlanta is about 779 miles. This result recommends three purchases totaling
> $78.19. It consumes 77.880 gallons, including the 50 gallons already in the starting tank.
> The purchase total is not the whole-trip cost. Without the starting fuel price, that estimate
> is unavailable. Each stop includes price, gallons, cost and fuel remaining.”

If the response differs, read the actual current figures. Do not use the script's numbers as
assertions about a changed provider response.

## 2:20–3:00 — Long-distance route

**Actions:** Send New York–Los Angeles; show distance, summary and stop count.

**Say:**

> “The coast-to-coast route is about 2,810 miles. The default minimum-cost result has 17 stops
> and $698.65 in purchases. Some top-ups save only cents. The optional two-dollar minimum-savings
> policy returns 11 stops for $2.09 extra in the audited result. That policy is greedy; it is
> separate from the default objective and does not guarantee the fewest stops.”

Do not edit and send extra requests if this would exceed the segment; the practical comparison
is recorded in the QA report and can be pointed to there.

## 3:00–3:40 — Interactive dashboard

**Actions:** Switch to the prepared Dallas dashboard. Select a card and then a different map
marker, show the popup and fit control. Briefly show vehicle settings; avoid a slow full-page
scroll or changing every field.

**Say:**

> “The dashboard uses the same Django API. Cards and map markers select each other, and the
> summary distinguishes purchases from total fuel cost. These markers are approximate Census
> town points because the CSV has no exact coordinates. Actual pump locations, road access and
> detours are unverified. The map labels this uncertainty.”

## 3:40–4:30 — Architecture and optimization

**Actions:** Show the four app folders, then the optimizer source. Do not read code line by line.

**Say:**

> “Django separates routing, station data, optimization and shared API handling. Location
> resolution is offline. Candidate stations are filtered around the route without calling
> a routing API for each station. The optimizer is pure Python. On a fixed route, it buys only
> enough to reach a cheaper reachable station; otherwise it fills the tank. The implementation
> tracks fuel lots and refunds unused purchases. Every plan is replayed to check range and
> capacity, and its costs are compared with an independently formulated dynamic-programming
> solver in the tests.”

## 4:30–4:50 — Caching, tests and assumptions

**Actions:** Show the QA/checklist test summary, then end recording by 4:50.

**Say:**

> “Successful routes are cached for seven days. All 416 backend and 36 frontend tests pass;
> live routing was checked separately. Stations are approximate, prices are static, and the
> model has no fuel reserve. Thank you.”

## After recording

Watch the entire video. Confirm the duration is below five minutes, text is readable, no
secrets are visible, and the shared link works for a reviewer without your account. Add the
actual GitHub and Loom links to the submission checklist only after they exist and are checked.
Recording, upload, link sharing and submission remain manual steps; none is performed by this script.
