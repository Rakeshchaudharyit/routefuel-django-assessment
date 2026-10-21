# M6 — Interactive Map & Live Django API Integration

Verified 21 October 2026. M6 implementation complete; M7 not started.

1. **Repository:** `/Users/rakesh/Projects/routefuel`. Extended the existing M5 frontend.
2. **Git status:** HEAD is the M5 preservation commit; M6 frontend/tests/documentation remain
   uncommitted for review. The inherited `frontend/.env.example` remains untracked and was
   excluded from the commit as requested. No unrelated changes were included. No push,
   history rewrite or amendment was performed. Django source and API contract have no diff.
3. **M5 preservation:** `13fac92` — `M5: professional dashboard foundation and typed API client`.
   Before that commit, all seven M5 tests, strict TypeScript, ESLint and production build passed.
   The commit contains only the intended M5 frontend/configuration/documentation, excluding
   environment files, secrets, dependency directories and generated build artifacts.
4. **Files:**
   - Updated `frontend/README.md`, `package.json`, `package-lock.json`, `src/app/globals.css`.
   - Updated `src/components/layout/app-shell.tsx` (version label only).
   - Updated route planner `dashboard.tsx` and `route-form.tsx`, map `route-map.tsx`,
     `fuel-stops/fuel-stops.tsx`, `trip-summary/trip-summary.tsx`, and `lib/api/client.ts`.
   - Added `src/components/map/route-layer.ts` and `src/lib/api/validation.ts`.
   - Added `vitest.config.ts`, `tests/integration.test.tsx`, `tests/validation.test.ts`,
     and `tests/fixtures/optimized.json` (all under `frontend/`).
   - Preserved M5 transport assertions in `tests/api-client.test.mjs`; updated its loader for
     the validation module and supplied a complete fixture for the now-validated endpoint.
   - Updated `docs/milestones.md`; added this report.
5. **API integration:** real POST `/api/v1/routes/optimize/`, exact documented city/state,
   vehicle and optional stop-policy schema; `geometry_detail: simplified`. Optional starting
   fuel price enables whole-trip cost. No requests on keystrokes. Pending submissions are
   disabled; deliberate rapid follow-ups queue with loading feedback to maintain a 1.1-second
   request interval. Deadlines, abort cleanup, health checks and Django error details remain.
   Runtime checks reject missing/malformed geometry, non-finite coordinates, invalid decimal
   representations, missing summary fields and duplicate/unordered stops before rendering.
6. **Route rendering:** a single MapLibre instance survives requests and selection changes.
   The actual GeoJSON line is passed through unchanged into one source; subsequent successes
   call `setData`. Teal route with a white outline, distinct A/B endpoints, bounds fitting on
   new results/resize, and a fit-route control. Sources, layers, listeners, popups and markers
   are cleaned up on unmount/retry. Backend attribution and OSM/CARTO attribution are retained
   in one control. No route geometry is fabricated in the application.
7. **Fuel markers:** numbered in the API's travel order using returned station coordinates.
   Popups show name, address, city/state, price, gallons, purchase cost, route mile and accuracy.
   Approximate town points have restrained dashed halos and geographic uncertainty areas
   derived from `uncertainty_miles`. These are town-size estimates, not verified station
   boundaries, detours or guaranteed accuracy. Exact access and detour distance are unverified.
   Popup text and routing attribution are escaped rather than treated as trusted HTML.
8. **Selection:** card buttons select the matching marker and popup and bring the map into
   view; marker buttons highlight and reveal the matching card. Both paths use a shared OPIS
   ID, `aria-pressed`, keyboard activation and visible focus. Selection does not recreate the
   map, sources or markers. Camera movement and selection scrolling are immediate. Marker
   click propagation is stopped so the map does not immediately dismiss its new popup.
9. **Trip summary:** displays API distance, driving time, gallons consumed/purchased,
   remaining fuel, stop count, purchases at stops and conditional whole-trip cost. Decimal
   strings retain all backend digits. Missing data never becomes zero. The backend cost note
   is shown with technical field names replaced by readable labels. No fuel optimization,
   station mile markers or fuel-cost calculations are duplicated in React.
10. **Errors/empty states:** handles disconnected Django, routing unavailable/timeouts,
    validation/location failures, no road route, infeasible fuel plans, malformed/empty
    geometry and no stops. A previous valid map/summary remains during loading/failure,
    explicitly labelled as the previous plan; a failed request never masquerades as its new
    result. A zero-stop journey is successful. Real invalid-destination and backend-outage
    browser checks retained the previous plan and its five markers.
11. **Performance:** live New York–Los Angeles returned 3,792 simplified coordinates and
    17 stops. One canvas and 19 markers were observed in the browser; replacing it with
    Dallas–Atlanta left one canvas and five markers, and zero-stop results left two markers.
    Unit tests also exercise a synthetic 20,000-point line in one source insertion and verify
    source reuse/marker removal. Validating the real 3,792-point response in Node v20.20.2
    took median **0.051 ms**, p95 **0.068 ms** over 100 samples after 20 warm-ups. This is a
    validator measurement, not a browser rendering/FPS benchmark. No formal FPS benchmark
    was performed. Cached cross-country HTTP request: **20.75 ms**; fresh: **1,388.87 ms**.
12. **Responsive/browser verification:** visually checked 1440px desktop, 1280px laptop,
    768px tablet and 390px mobile using real Django responses. No horizontal overflow;
    forms, map controls, summaries, cards and selection work. Tablet stacks the map above
    summary/cards. Mobile stacks all panels and uses collapsible navigation. Desktop/tablet
    long stop lists scroll internally; mobile lists stack normally. Popup clipping and
    immediate-dismissal issues found during testing were fixed and retested. No unexpected
    runtime warnings/errors were observed in the final successful browser session. Temporary
    preview servers were stopped after verification, including a deliberate outage check.
13. **Tests:** **35 passing**: seven preserved M5 tests plus 28 Vitest tests. Tests are
    deterministic and mock transport/MapLibre only in the test environment. Fixtures combine
    the documented examples and use abridged stand-in geometry; they are never application
    data and are not evidence of live provider success.

    | Requested coverage | Verification |
    |---|---|
    | Successful optimized response | Runtime validation + dashboard success |
    | Geometry rendering | GeoJSON source/line assertions |
    | Origin/destination markers | Exact coordinates and accessible labels |
    | Multiple stop markers | Numbering, order and exact API coordinates |
    | Zero-stop journey | Successful summary/cards + endpoint-only update |
    | Card selection | Matching pressed marker and camera/popup |
    | Marker selection | Matching pressed card and popup details |
    | Summary formatting | API values, USD precision, duration and remaining fuel |
    | Unknown whole-trip cost | Unavailable state and note; no fabricated zero |
    | Invalid responses | Missing/empty geometry, invalid coordinates, malformed fields |
    | Backend unavailable | Mocked network error + real browser outage |
    | Routing unavailable | Deterministic Django error response |
    | No feasible plan | Deterministic Django error response |
    | Form submission | Required/vehicle validation and exact payload/stop policy |
    | Loading | Pending controls and visible feedback |
    | Repeated routes | Source reuse, marker cleanup, queued retry, retained valid plan |
    | M5 regression tests | All seven preserved assertions pass |

14. **TypeScript:** `npm run typecheck` passes with strict mode.
15. **ESLint:** `npm run lint` passes without errors or warnings.
16. **Production build:** `npm run build` passes with the existing Webpack build command;
    outputs `/`, `/api-documentation` and the framework not-found route. Test tooling is
    development-only: Vitest, React Testing Library and jsdom. No new production dependencies.
17. **Live Django/OSRM verification:** **passed**, including fresh provider access and cache
    reuse. The earlier M4 connectivity block no longer reproduces on this local machine.
    Initial `verify_routing` reached OSRM but failed optimization because the local station
    table was empty. Ran the existing idempotent CSV importer: 6,626 stations, 6,228 with
    approximate Census coordinates, 398 unresolved. Only ignored local database/cache data
    changed; no backend code, settings files or API contract changed. Re-running the existing
    `manage.py verify_routing` passed every check: direct OSRM, fresh Django route,
    repeated cached route and default-truck optimized fuel plan.

    | Route / request | Distance | Display points | Stops | Stop purchases | HTTP time | Cache / external calls |
    |---|---:|---:|---:|---:|---:|---|
    | Dallas → Atlanta, cached | 778.80 mi | 800 | 3 | $78.19 | 10.39 ms | true / 0 |
    | Dallas → Atlanta, repeat | 778.80 mi | 800 | 3 | $78.19 | 20.96 ms | true / 0 |
    | New York → Los Angeles, fresh | 2,810.37 mi | 3,792 | 17 | $698.65 | 1,388.87 ms | false / 1 |
    | New York → Los Angeles, repeat | 2,810.37 mi | 3,792 | 17 | $698.65 | 20.75 ms | true / 0 |

    The fresh Dallas route in `verify_routing` contained 8,177 full coordinates and took
    481 ms through Django (direct provider: 773 ms). Dallas stops: Canton 5.718 gal/$15.87,
    Lindale 2.731 gal/$7.67, Meridian 19.431 gal/$54.65. Live browser checks confirmed both
    route lines, endpoint/stop markers, summaries, updates and selection. Adding a $3.199
    starting price yielded $238.14 whole-trip fuel cost. A 1,000-mile vehicle with 100 starting
    gallons yielded zero stops, 22.120 gal remaining, $0.00 purchases and $249.14 whole-trip
    cost. These figures came from Django; they were not calculated or substituted in React.
18. **Remaining limitations:** stations still mark towns and use static prices; confirm pump
    address and access. Public map tiles/provider require connectivity; current success does
    not establish availability on another network. Overlapping markers on long routes can be
    selected through cards or by zooming. The form exposes city/state inputs; coordinate input
    is supported by API types but has no dedicated control. Tests mock WebGL; real rendering
    was checked separately in the in-app browser. No formal browser frame-rate benchmark.
19. **M6 acceptance checklist:**
    - [x] M5 verified and preserved locally before M6 changes.
    - [x] Real typed/validated route optimization, vehicle settings and optional stop policy.
    - [x] Actual GeoJSON line, bounds fitting, distinct endpoints and ordered stop markers.
    - [x] Approximate location labels/areas and complete attribution.
    - [x] Two-way keyboard-accessible card/marker selection and station details.
    - [x] Complete summary, remaining fuel, separate purchases and whole-trip cost.
    - [x] Initial/loading/error/zero-stop states and retained previous valid results.
    - [x] No duplicate map instances/layers/markers across repeated results.
    - [x] Deterministic automated tests and unchanged M5 assertions.
    - [x] Fresh real OSRM/Django success, multi-stop route and repeat-cache verification.
    - [x] Desktop/laptop/tablet/mobile browser checks.
    - [x] Strict TypeScript, ESLint, complete frontend tests and production build pass.
    - [x] README, milestones and integration report updated.
    - [x] No backend source/API changes, push, history rewrite, authentication or billing.
20. **Readiness for M7:** M6 is ready for the separately authorized testing/independent-review
    milestone. M7 has not been started. Before Loom, re-run the documented live verification
    on the demonstration machine/network rather than relying only on cached or fixture data.
