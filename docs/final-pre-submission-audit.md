# RouteFuel — final pre-submission audit (M9)

Audited 22 October 2026 against the Spotter AI assignment. Everything below was executed in this
audit unless marked otherwise. Nothing was committed, pushed or published.

**Verdict: READY FOR GITHUB SUBMISSION**, once the pre-push steps in "Remaining blockers" are done
(commit the reviewed uncommitted work; rerun Vitest and the Next.js build on the Mac).

## How the audit was run

| Area | Where it ran | Notes |
|---|---|---|
| Live API and OSRM | Your Mac's running Django (`127.0.0.1:8000`), called from a page on the same origin | Real OSRM responses; cache was empty at the start |
| Backend tests and checks | Linux container on a byte-identical copy of `backend/` (97 files, matching manifest hash) | The Mac's `.venv` (Homebrew Python) cannot be executed from the audit tools |
| Optimizer reference check | Container, with SciPy `linprog` (HiGHS) as an independent LP | Real candidate sets came from a copy of your database, using the routes cached during the live tests |
| Admin UI | Headless Chromium on an isolated server with a disposable database copy and a temporary superuser (both deleted) | Your development database was only read |
| Frontend | Linux VM on a copy of `frontend/` | TypeScript, ESLint and Node tests ran; Vitest and `next build` need macOS-native binaries |

Neither audit environment can reach OSRM, PyPI or npm directly. Live routing therefore went
through your Mac's Django.

## Requirements compliance

| # | Requirement | Status | Evidence |
|---|---|---|---|
| 1 | Django API, US start/finish | Pass | `POST /api/v1/routes/optimize/`; "City, ST" or coordinates; non-US state → 422 |
| 2 | Route suitable for a map | Pass | GeoJSON LineString (8,177 points for Dallas–Atlanta); `simplified` option for drawing |
| 3 | Optimal fuel stops | Pass | Matches an independent LP optimum on real routes (difference ≤ 1e-13) |
| 4 | Optimize for cost | Pass | Objective = money spent at stations; the stop-reduction policy is opt-in only |
| 5 | Use supplied CSV | Pass | 8,151 rows → 6,626 US stations (620 Canadian rows skipped as out of scope, 905 merged duplicates) |
| 6 | 500-mile range | Pass | Default `range_miles` 500; reachability enforced, infeasible gaps → 422 |
| 7 | 10 MPG | Pass | Default `mpg` 10 → 50-gallon tank |
| 8 | Total money spent on fuel | Pass, with an interpretation note | `total_purchase_cost`; the whole-trip estimate needs a starting-fuel price (see M-2) |
| 9 | Multiple stops | Pass | 3 stops (Dallas–Atlanta), 17 stops (NY–LA) |
| 10 | Free routing API | Pass | Public OSRM demo server, with identifying User-Agent and attribution |
| 11 | Minimal routing calls | Pass | Uncached request = 1 provider call, cached = 0; no per-station routing |
| 12 | Fast results | Pass | Server processing ≈ 37 ms (Dallas–Atlanta) after an OSRM call of 0.35–3.5 s; cached 18–115 ms |
| 13 | Latest stable Django | Pass | Django 6.1.2 pinned and installed; latest release (security release of 6 October 2026) |
| 14 | GitHub source | Pending (manual) | Repository is safe to publish after the steps below |
| 15 | Loom under 5 minutes | Pending (manual) | Script targets 4:50 and covers all requested points |

## Repository status

- Branch `main`, last commit `8226559` (M8). The admin redesign and the fuel-station import
  are still **uncommitted**: 10 modified files and untracked paths for the admin app, templates,
  static files, tests, migration `fuel/0002_stationimport` and docs. All were preserved. This
  audit only edited `docs/loom-demo-script.md` and `docs/submission-checklist.md`, and added
  this report.
- Ignored and untracked as intended: `.env`, `backend/db.sqlite3`, `.venv/`,
  `frontend/node_modules/`, `frontend/.next/`, `*.tsbuildinfo`, `frontend/.env.local`.
  126 tracked files contain no database, environment, cache or build output.
- Secret scan of tracked and untracked files found only the documented insecure fallback
  `SECRET_KEY` used when `DEBUG` is on. The real `.env` is ignored.
- Development database: migrations `fuel 0001/0002`, `routing 0001`, `admin`, `sessions` applied.
  Stations: 6,626 with unique OPIS IDs; 6,228 town-level (Census 2010 gazetteer, radius
  1.0–15.4 mi) and 398 unresolved with no coordinates; no price violates max ≥ retail; no
  coordinates outside a US bounding box. It holds one applied and one unconfirmed admin import
  made outside this audit.

## Backend verification

| Command | Result |
|---|---|
| `pytest -q` | **511 passed** (≈ 55 s) |
| `ruff check .` / `ruff format --check .` | Pass / 73 files formatted |
| `manage.py check` | No issues |
| `makemigrations --check --dry-run` | No changes |
| `showmigrations` (development DB, read from `django_migrations`) | `fuel.0001`, `fuel.0002_stationimport`, `routing.0001` applied |

API behavior verified live on your Mac:

| Request | Status | Result |
|---|---|---|
| `GET /api/v1/health/` | 200 | `{"status":"ok","service":"routefuel-api"}` |
| `POST /api/v1/routes/` Dallas–Atlanta | 200 | 778.8 mi, 843.9 min, cached, 0 provider calls |
| Missing fields / `"Dallas"` / bad vehicle values | 400 | Field-level errors in the `{"error": {code, message, details}}` envelope |
| `Atlantis, ZZ` / `Notarealtown, TX` | 422 | `location_not_found` with field and details |
| Same start and finish | 422 | `same_location` |
| 30-mile range | 422 | `no_feasible_fuel_plan`, gap 40.3 mi at mile 84.5 |
| `GET` on optimize | 405 | JSON envelope, not HTML |

The API is usable without the dashboard: DRF browsable API in DEBUG, JSON otherwise, plus the Postman collection.

## Real routing results (live OSRM via the Mac)

| Route | Distance / duration | Stops | Purchases | Provider calls | Client time | OSRM time | Local processing |
|---|---|---|---|---|---|---|---|
| Dallas, TX → Atlanta, GA (fresh) | 778.8 mi / 843.9 min | 3 | $78.19 (27.880 gal) | 1 | 984 ms | 947 ms | ≈ 20 ms matching + 0.3 ms optimization |
| Same, repeated | same | 3 | $78.19 | 0 (cached) | 28 ms | — | 4 + 8 + 2 ms |
| New York, NY → Los Angeles, CA (fresh) | 2,810.37 mi / 3,019.4 min | 17 | $698.65 (231.035 gal) | 1 | 3,590 ms | 3,539 ms | 29 ms matching + 0.6 ms optimization |
| Same, `$2` practical-stop policy | same | 11 | $700.74 | 0 | 115 ms | — | 81 ms policy |
| Dallas, TX → Austin, TX (fresh) | 195.6 mi / 209.9 min | 0 | $0.00; 30.44 gal left | 1 | 374 ms | 351 ms | 14 ms |
| Dallas–Atlanta, empty tank | 778.8 mi | 5 | $217.37 (77.881 gal) | 0 | 31 ms | — | — |
| Dallas–Atlanta, starting price $3.00 | 778.8 mi | 3 | $78.19 purchases; $228.19 estimated whole trip | 0 | 18 ms | — | — |

All earlier reference figures (778.8 mi / 3 stops / $78.19; 2,810.37 mi / 17 stops / $698.65;
practical policy 11 stops / $700.74) were reproduced exactly. Each fresh route made exactly one
OSRM request.

## Optimization correctness

- Model: 500 mi / 10 MPG = 50-gallon tank, starting full by default (configurable 0–capacity),
  continuous gallons, objective = money spent at stations. Starting fuel is treated as already
  paid, and leftover fuel has no value. The algorithm is the classical "fill up, refund the
  dearer fuel" greedy (a sort plus a lot queue: O(n²) worst case, under 3 ms on the longest real
  route), and every plan is replayed to check range, capacity,
  non-negative purchases and the fuel balance.
- Independent check: an LP (SciPy HiGHS, written for this audit) on **4,000 random instances**.
  These included equal prices, duplicate candidates at the same mile, stations at mile 0 and at
  the destination, empty, partial and full tanks, and three range/MPG combinations. Result:
  **0 feasibility mismatches, 0 cost mismatches**, worst relative difference 9.6e-15. No
  purchase was non-positive or non-finite, and remaining fuel was never negative.
- Real candidate sets: Dallas–Atlanta 126 candidates, LP $78.1857 = optimizer $78.1857;
  NY–LA 399 candidates, $698.6452 = $698.6452; Dallas–Austin $0 = $0.
- Money uses `Decimal` throughout. Gallons are rounded to 0.001 and costs half-up to the cent per
  stop, so the total is the sum of the rounded line items (exact Dallas–Atlanta $78.1857 → $78.19).
- Input validation rejects non-finite, boolean or out-of-range vehicle values and impossible
  starting fuel (400).
- Practical stops: on NY–LA, the 6 extra stops in minimum-cost mode save $2.09 combined (about
  $0.35 each). They are not meaningful savings in practice, so the opt-in `$2` policy is
  reasonable. It is greedy and does not change the default objective. Minimum-cost plans can
  include small top-ups (smallest NY–LA purchase 1.28 gal; 0.61 gal with an empty start).
- The algorithm was not modified; no defect was reproduced.

## Fuel-station data

OPIS IDs are unique (database constraint and 6,626 distinct values). Prices are stored exactly
with up to 8 decimals (range $2.687–$6.399). CHECK constraints cover price order, coordinate
ranges and geolocation consistency. Duplicate CSV rows are merged by documented rules, and
conflicting duplicates are rejected. Coordinates are town points (Census gazetteer), **not
truck-stop positions**. Station matching takes 7–30 ms per route on the indexed bounding-box query.

## Admin CSV/Excel import

- Present on the Mac: `admin_import.py`, `station_import.py`, migration `0002_stationimport`
  (applied), templates and static files.
- 71 dedicated tests (all passing) cover:
  - the button, anonymous redirects and permission rules (separate add/change checks, uploader-only access)
  - CSRF, CSV, XLSX, template download, disguised, macro and oversized files
  - new / update / unchanged / partial-column / blank-cell behavior
  - duplicates, invalid-row reporting and the error-report CSV with formula neutralization
  - previews that write nothing, all-or-nothing transactions, double submission and stale previews
  - geolocation preservation and invalidation, the station-data version used by the route planner
  - compatibility with the CLI importer
- Browser-verified earlier on 22 October on a disposable copy (login, button, upload, preview,
  error report, double-click → one POST, results, repeat upload, logout).
- Measured on the real 8,151-row file: CSV preview 0.3 s, XLSX preview 1.5–2.0 s, first import of
  6,626 stations including geolocation 2.7–2.9 s, unchanged re-import confirm 0.4 s, all-station
  price update 5 s (SQLite `bulk_update`).

## Admin UI and security

- `/` → `/admin/` → login redirect verified. Login, logout (POST + CSRF), session cookie settings
  (HttpOnly, SameSite=Lax, `/admin/` path, Secure when DEBUG is off) and model permissions are
  covered by `tests/test_admin.py` and passing.
- Mobile check at 390 px (index, station list, change form, add form, import): page scroll width
  equals the viewport and no controls fall outside it. The account bar is a single 22 px line
  in its own header row. **Both earlier Codex issues (compressed account header, clipped form
  controls) are fixed.** Desktop at 1440 px has no overflow.
- Cosmetic only: the "+" icon touches the "Add fuel station" label, and on mobile the filters
  appear before the station list.

## Frontend

| Check | Result |
|---|---|
| `tsc --noEmit` | Pass (VM copy) |
| `eslint .` | Pass |
| `node --test tests/*.test.mjs` | **7/7 pass** |
| Vitest (29 tests) and `next build` | **Not runnable in the audit environment** (macOS-native `rollup`/`swc` binaries); last passed in M8. There are no frontend changes since M8 (`git status` shows none) |

The dashboard UI was not re-driven in a browser in this audit. The built-in browser pane blocks
cross-port requests, and the Chrome extension was not connected. M7/M8 reports cover the map,
selection, costs, errors and responsive layout.

**CORS:** project defaults and `.env.example` allow both `http://localhost:3000` and
`http://127.0.0.1:3000`, limited to `/api/*`, with no wildcard. Your **local `.env` currently
allows only `http://localhost:3000`**, while `npm run dev` binds `127.0.0.1`. See M-1.

## Security

No secrets tracked, `.env` ignored, `DEBUG` off by default, and the secret key is required when
`DEBUG` is off. CORS is restricted. Admin security is native Django (hashing, sessions, CSRF,
validators). Uploads are capped at 5 MB, their content is sniffed, macros are rejected,
formulas are not evaluated, zip expansion is limited, uploads are never stored on disk, and the
CSV export is formula-safe. Unhandled API errors are logged and returned as a generic 500
without stack traces. No credentials appear in log calls. A dependency advisory scan
(pip-audit / npm audit) could not run here because those advisory services are unreachable.
Django is on the latest security release.

## Documentation

README, API contract and architecture docs match the verified behavior. The limitations are
stated plainly: approximate town-level stations, unverified access and detours, static prices,
no fuel reserve, starting-fuel valuation, and public-OSRM availability. **Fixed in this audit:**
the Loom script and submission checklist still quoted 416 backend tests. The README's 416/36
line is labeled as M8 history and kept.

## Issues

| ID | Severity | Issue | Action |
|---|---|---|---|
| M-1 | MEDIUM | Local `.env` CORS lacks `http://127.0.0.1:3000` (repository defaults are correct) | Set `DJANGO_CORS_ALLOWED_ORIGINS=http://localhost:3000,http://127.0.0.1:3000` and restart Django; not changed by the audit (local secrets file) |
| M-2 | MEDIUM | "Total money spent" defaults to purchases with a full, already-paid tank ($78.19); the whole-trip figure needs `starting_fuel_price_per_gallon` or an empty tank ($217.37) | Documented and in the Loom script; say it explicitly in the video |
| M-3 | MEDIUM | Admin redesign and import are uncommitted | Review and commit before pushing, otherwise GitHub will not contain them |
| L-1 | LOW | No LICENSE file (data sources are attributed in `backend/data/reference/SOURCE.md`) | Optional for an assessment repository |
| L-2 | LOW | Minimum-cost plans include sub-2-gallon top-ups | Opt-in practical-stop policy exists; documented |
| L-3 | LOW | Admin cosmetics (add-icon spacing, mobile filter order) | Optional |
| L-4 | LOW | Dependency advisory scan not run | Run `pip-audit` / `npm audit` on the Mac if desired |

No CRITICAL or HIGH defects were found, so no application code was changed.

## Remaining blockers before pushing

1. On the Mac: `cd frontend && npm test && npm run build` — confirm 36 tests and the build.
2. Review, then commit the uncommitted work (not done by this audit).
3. Optionally fix M-1 in `.env` before recording the dashboard.
4. Record the Loom (script target 4:50) and add the GitHub and Loom links to the checklist.

## Recommendation

The application meets every functional requirement, and the core claims were reproduced
against live OSRM and an independent optimizer check. After steps 1–2 it is ready to publish.

**READY FOR GITHUB SUBMISSION**
