# M7 — Final QA and technical review

Date: 22 October 2026 (Asia/Kolkata). Repository: `<repository-root>`.

## Executive summary

M7 passes the local assessment checks, with limitations below. M6 was reviewed and preserved
first in local commit `49b4c19` (`M6: live route maps and interactive fuel-stop selection`),
after its 35 tests, TypeScript, lint and build passed. M5 remains `13fac92`; history and
commit authorship were not rewritten. This report records M7 completion; M7 was subsequently
preserved in local commit `d44d473` before M8 preparation. See the [submission checklist](submission-checklist.md)
for current publication status. Nothing was pushed during M7.

The default optimizer was not changed. Review and independently formulated DP comparisons
support minimum continuous purchase cost for the fixed-route model. This does not establish
optimal real-world stops: the database has town coordinates, not verified pump positions,
and the model ignores road access, detours, reserve fuel and stopping time.

This is a Codex technical audit using an independent reference solver. It does not claim a
separate Claude or human review/sign-off.

## Backend audit

Reviewed request serializers, views, error handling, OSRM parsing, route service/cache,
station query/matching, optimizer and replay validation, fuel serialization and configuration.
Health returns 200 without provider calls. Both POST endpoints share location resolution and
route cache, return GeoJSON longitude/latitude LineStrings, and use a consistent JSON error
envelope. Automated coverage exercises invalid JSON/media/methods, field validation, provider
timeouts/outages/malformed replies, cache failures/coalescing, US boundaries and feasibility.

Live invalid Census place returned 422 `location_not_found`; invalid MPG returned 400
`invalid`; a 10-mile-range journey returned 422 `no_feasible_fuel_plan`; mainland–Hawaii
returned 422 `route_not_found`. Provider failure statuses (502/503/504) are automated tests,
not intentionally induced public-provider outages.

Successful routes are cached by provider/server/directional coordinates. Fresh audited routes
made exactly one counted real provider call each; repeats made zero. There are no per-station
routing requests. Errors are not cached. A process-local memo accelerates station matching;
its invalidation depends on the station-data version. Coalescing reduces concurrent successful
calls but failed holders can allow successive waiters to retry; there is no global one-retry
budget. A failed/unavailable cache falls back to uncached work.

## Optimization correctness

Defaults are 500 miles per tank, 10 MPG, 50-gallon capacity, full starting tank. The optimizer
uses ordered fuel lots: burn the oldest fuel, remove unconsumed purchases when cheaper fuel
appears, and refund unconsumed purchased fuel at arrival. This implements the fixed-route
rule of buying only enough to reach the first cheaper reachable station, otherwise filling.
Starting fuel is already owned and is consumed before new purchases. Every returned raw plan
is replay-checked for order, consumption, capacity and reachability.

The existing independent DP enumerates fuel states rather than reproducing the lot algorithm.
Its 10,000 integer-grid and 1,000 tenth-gallon random cases all pass. M7 adds **300 seeded
thousandth-gallon cases**, including equal prices, duplicate mile markers, fractional
purchases, empty/partial starts, high price precision and infeasible instances. Three added
cases check the 500-mile boundary at −0.00001, exactly, and +0.00001 miles. Existing tests
cover duplicate candidates, ordering, negative quantities and counterexamples to naive greedy
rules. Floating gallons use an absolute 1e-9-gallon tolerance; money uses Decimal.

The objective is continuous purchase cost, not minimum stops or minimum sum of rounded cents.
Equal-cost plans need not use the fewest stops. No optimizer logic was modified. The prior
O(n log n) runtime claim was too strong: sorting is O(n log n), but repeated sums of remaining
lots make the pass O(n²) in the worst case. Actual 399-candidate optimization was 0.61 ms.

## Real routing verification

The audit script wraps the configured real provider only to count and time calls; it does
not supply replacement geometry. It clears only audited route entries, uses the real local
station database and spaces network calls at least 1.1 seconds apart. Four real calls were
made: three fresh drivable routes and one unreachable route.

| Route | Miles | Stops | Fuel purchases | Fresh / repeat calls |
|---|---:|---:|---:|---:|
| Dallas → Atlanta | 778.80 | 3 | $78.19 | 1 / 0 |
| New York → Los Angeles | 2,810.37 | 17 | $698.65 | 1 / 0 |
| Dallas → Austin | 195.60 | 0 | $0.00 | 1 / 0 |

Dallas–Austin consumed 19.560 gallons and retained 30.440 gallons. The two longer default
plans consumed all 50 gallons of starting fuel and arrived with zero modeled reserve.

Reproduce from the repository root with the local virtual environment and imported database:

```sh
.venv/bin/python docs/qa/m7_audit.py > /tmp/routefuel-m7-live-results.json
.venv/bin/python docs/postman/run_collection.py --base-url http://127.0.0.1:8000
```

The first command makes real external calls and mutates the relevant route cache entries.
Saved results: [live evidence](qa/m7-live-results.json); source: [audit script](qa/m7_audit.py).
These are one-run measurements, not latency percentiles or permanent provider guarantees.

## Why 17 stops, and the practical alternative

An independent reachability DP over the 399 live candidates found **five minimum refueling
stops** in the approximate model. A distance-only lower bound is also five: a full starting
tank plus five refills can cover at most 3,000 miles. One feasible five-stop chain has OPIS
IDs 61421, 5230, 65284, 70626 and 3593 at miles 484.5157, 981.6323, 1464.0345, 1956.6176 and
2341.9912. Every gap, including the last 468.38 miles, is within 500 miles. This demonstrates
feasibility, not the cheapest five-stop plan or verified real-world road access.

| Minimum savings per stop | Stops | Purchase cost | Difference from default |
|---|---:|---:|---:|
| No policy | 17 | $698.65 | — |
| $0.10 | 14 | $698.69 | +$0.04 |
| $1.00 | 12 | $699.22 | +$0.57 |
| $2.00 | 11 | $700.74 | +$2.09 |
| $5.00 / $10.00 | 11 | $700.74 | +$2.09 |

Some stops make negligible savings. Excluding OPIS 52548 or 72572 changes exact cost by only
floating arithmetic noise (~1e-15 dollars); excluding 70467 or 69840 adds roughly 4.1 or 5.0
cents. Marginal effects are not additive, and some exclusions substitute another stop without
reducing stop count. The existing greedy policy removes a used station only when reoptimization
reduces stop count within the per-removal threshold. It can get stuck at 11 even though five
is feasible. The threshold is not a total extra-cost budget. The default objective is intact.

## Fuel cost and rounding

Consumption, starting fuel used, purchases and remaining fuel are separate API quantities.
Each line costs price × gallons rounded to 0.001, then HALF_UP to cents; the purchase total
is exactly the sum of line costs. The audit checks that identity using Decimal.

A full starting tank is not free. Without a supplied starting-fuel price, whole-trip cost is
explicitly `null` / `unavailable` when starting fuel is consumed. With Dallas–Atlanta and
$3.199/gallon supplied, 50 gallons of starting fuel are valued at $159.95; purchases are $78.19
and the displayed whole-trip estimate is $238.14. The real browser confirmed this distinction.

Serialization rounds gallons per stop. New York's displayed purchases sum to 231.035 gallons
against 281.037 consumed minus 50 starting: a 0.002-gallon rounding difference. Raw plans pass
replay checks; displayed quantities are not an exact physical replay. Tiny positive purchases
can display as 0.000 gallons or $0.00. Money totals still add exactly.

A new deterministic equal-price counterexample produces effectively equal exact costs, but
$78.02 with two rounded purchases and $78.01 with one. Consequently a practical policy can
legitimately return `extra_cost: "-0.01"`. The frontend incorrectly rejected this valid payload;
M7 accepts signed policy deltas while retaining nonnegative validation for prices/purchases.

## Station-location accuracy

The real database has **6,626 stations: 6,228 city approximations, 398 unresolved, zero verified
address coordinates**. Unresolved stations are excluded. The matching corridor is five miles
plus each town's uncertainty estimate (at least one mile). Matching projects onto a thinned
route line and scales cumulative mileage to the provider distance. Display geometry is
simplified separately and is not used to recalculate fuel totals.

Town points can put several stations at the same location, admit stations far from actual
highway access, exclude a usable station, or assign the wrong visit on a looping route.
Uncertainty circles describe town-scale uncertainty, not guaranteed error bounds. Markers
show town points, not projected pump positions. Access direction, exits, detours, extra fuel,
truck restrictions and actual reachability are unverified. API metadata, map text, cards,
README and this report disclose those limitations. This remains the main assessment caveat.

## Frontend integration and browser QA

Used real Django at port 8000 and Next.js at `http://localhost:3000`, with no browser response
mocking. Checked API-connected status; Dallas–Atlanta, Dallas–Austin and New York–Los Angeles;
real OSRM map geometry; ordered markers/cards; card-to-marker and marker-to-card selection;
popup uncertainty and purchases; fit control; route recalculation; summary totals; starting
fuel price; optional $2 policy; and unknown-city error feedback preserving the previous map.
A rapid follow-up visibly showed disabled controls, loading feedback and the previous-plan
banner. At 390 px, the 11-stop route had one map canvas, 11 cards and no document overflow
(client and scroll width both 390). Mobile station selection opened the corresponding popup.
Desktop was also checked at 1440 px. Captured browser warning/error logs were empty before
the deliberate server shutdown. After shutdown, submitting again showed API-disconnected
and connection-error feedback while preserving the 11-stop $700.74 result. QA servers were
then left stopped.

Minor UI limitation observed: after selecting an edge station and then fitting the entire
cross-country route, the still-open popup can clip at the map boundary. Reselecting the station
centers it, or closing the popup restores the overview. This does not alter route or costs.

Automated map tests use a MapLibre double; they separately cover lifecycle cleanup, malformed
geometry, 20,000-point routes, API errors/outages, zero stops, selection and queued retries.
M7 browser checks exercised real successful, invalid-location and backend-outage responses.
No FPS, browser CPU or production-browser rendering benchmark was performed.

## Performance

Measured in-process Django requests include middleware, serialization, database and real
network calls. They are not local HTTP round-trip measurements. The wrapper separately times
the actual provider call. The route stage can include provider rate-spacing wait, resolution
and cache work; it must not be described as pure network time.

| Route | Fresh API ms | Provider ms | Fresh matching ms | Pure optimization ms | Repeat API ms |
|---|---:|---:|---:|---:|---:|
| Dallas–Atlanta | 894.645 | 857.216 | 12.56 | 0.23 | 2.890 |
| New York–Los Angeles | 1038.689 | 694.315 | 30.83 | 0.61 | 5.066 |
| Dallas–Austin | 468.922 | 178.047 | 8.31 | 0.17 | 3.571 |

Fresh requests each recorded 14 database queries; repeats recorded two. Warm matching was
1.29–1.72 ms. New York's full route had 35,196 points, its display line 3,792. Parsing the
full JSON geometry plus obtaining/parsing the warm display line took 69.802 ms; this is not
an isolated cold simplification benchmark. The $2 practical policy took 47.255 ms in the
audit, including repeated optimization. The browser handled the actual simplified route
without an observed interaction failure; no quantitative rendering latency claim is made.

The separate Postman stdlib runner over actual local HTTP passed **8/8 expected statuses**.
Cached Dallas optimized took 27 ms, New York 116 ms in that run (full response/HTTP and
separate worker warmup differ from the in-process simplified audit). The runner does not
execute Postman's JavaScript assertions. Collection/environment were reviewed; no credentials
or environment values were added.

## Automated checks

| Check | Result |
|---|---|
| Backend pytest | **416 passed in 4.02 s** (392 preserved + 24 new) |
| Django system check | No issues |
| Migration drift check | No changes detected |
| Ruff check / format check | Pass; 65 backend files formatted |
| Frontend Node tests | 7 passed |
| Frontend Vitest tests | 29 passed |
| TypeScript `npm run typecheck` | Pass |
| ESLint `npm run lint` | Pass |
| Production `npm run build` | Pass (existing webpack build command) |
| Real HTTP collection runner | 8/8 statuses pass |

Backend tests deny external sockets. Their mocks are distinct from the counted live audit
and real browser checks. No existing tests were removed or weakened.

## Issues discovered and fixed

1. Very large JSON integer coordinates/vehicle fields could raise `OverflowError` and return
   500. Bounded coordinate checks and safe finite conversion now return field-level 400s.
2. Tiny MPG/range values could derive infinite or zero capacity. These overflow/underflow
   combinations now return 400 before routing.
3. Floating configuration accepted NaN/infinity, invalidating timeouts/corridor assumptions.
   `env_float` now requires finite positive values at startup.
4. Oversized provider distance/duration/coordinates could escape as 500. Conversion overflow
   is now classified as malformed-provider 502.
5. Frontend rejected valid negative rounded practical-policy deltas. Only this delta now
   accepts signed decimal strings; negative purchase totals remain rejected.
6. Docs had stale blocked-network/M7 status and overstated complexity/coalescing guarantees.
   Updated current status, setup consistency, rounding and practical-stop explanation.

The new backend defect tests were run before fixes (16 failed / one passed), then all 17
passed. The new frontend regression failed before its fix, then passed. Seven additional
optimizer audit tests add the fractional-grid, boundary and rounding coverage.

## Security and code quality

Configuration defaults to DEBUG off and requires a secret when DEBUG is off. The inspected
local development runtime has DEBUG on, localhost/127.0.0.1 allowed hosts and only
`http://localhost:3000` allowed by its CORS override. This is local demo configuration, not a
production deployment security certification. Provider timeout is configured, errors return
sanitized envelopes, and popup content is constructed as text/DOM rather than injected HTML.
Secrets/database/build outputs were not added. Dependency versions are locked; no dependency
upgrade was introduced. The optional production npm advisory request timed out at the
registry bulk-advisory endpoint, so dependency vulnerability status remains **unverified**.

## Files changed in M7

- `backend/apps/routing/{serializers,providers}.py`, `backend/config/settings.py`
- `backend/tests/test_m7_regressions.py`, `backend/tests/test_m7_optimizer_audit.py`
- `frontend/src/lib/api/validation.ts`, `frontend/tests/validation.test.ts`
- `README.md`, `frontend/README.md`, `docs/{architecture,api-contract,milestones}.md`
- This report, `docs/qa/m7_audit.py`, `docs/qa/m7-live-results.json`

The pre-existing untracked `frontend/.env.example` remains uncommitted and was not part of
M6 preservation or M7 edits. Ignored runtime caches/database/build outputs are not deliverables.

## Acceptance and submission readiness

- [x] M6 preserved separately; no push, history rewrite or M8 work.
- [x] Backend, station data, routing, API, optimizer, frontend and docs reviewed.
- [x] Real routes, fresh/cache call counts and error cases independently verified.
- [x] Independent solver comparisons and raw fuel replay pass; optimizer unchanged.
- [x] Practical stops and starting-fuel valuation explained and verified.
- [x] Real desktop/mobile integration plus automated checks pass.
- [x] Bugs fixed with regression tests; report and reproducible evidence saved.
- [x] Approximate location and performance/rounding limitations disclosed.

Ready for the human decision to begin M8, with town-level station accuracy prominently
explained in any demonstration. Recheck the live provider on the recording network. Exact
station geocoding, access/detour routing, reserve fuel, an exact stop-cost objective, popup
edge placement and a completed dependency advisory scan remain outside this completed M7
scope. No claim is made that every extreme finite numerical combination has been exhaustively
tested. M8 remains unstarted.
