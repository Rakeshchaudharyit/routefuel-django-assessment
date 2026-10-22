# Final snapshot report — 22 October 2026

Pre-GitHub snapshot and documentation review for RouteFuel. Nothing was committed, pushed,
published or recorded.

## Snapshot

| | |
|---|---|
| Project directory | `routefuel/` repository root (branch `main`, last commit `8226559`, plus uncommitted work) |
| Snapshot | `../routefuel-snapshots/routefuel-pre-github-2026-10-22.zip`, a sibling folder outside the repository |
| Checksum | `routefuel-pre-github-2026-10-22.zip.sha256` beside the ZIP. The value is also in the "Snapshot checksum" section at the end of this file; the copy of this report inside the ZIP was written before the checksum existed |
| Contents | `routefuel/` with every Git-tracked file plus every untracked, non-ignored file, filtered by a deny-list. Also `SNAPSHOT-MANIFEST.txt` (SHA-256 per file) and `SNAPSHOT-README.txt` (restore steps) |

**Included:** Django source (`config`, four apps, migrations `fuel/0001–0002`, `routing/0001`),
management commands, admin templates and static files, the CSV/XLSX import, 511 backend
tests and fixtures, and the Next.js source, tests and `package-lock.json`. Also the dependency
manifests, `.env.example` and `frontend/.env.example`, the Postman collection, environment and
runner, all docs, the reference datasets, and the employer fuel-price CSV.

**Excluded:** `.env`, `frontend/.env.local` (absent), `.venv/`, `node_modules/`, `.next/`,
`__pycache__/`, `.pytest_cache/`, `.ruff_cache/`, `staticfiles/`, `*.sqlite3` (the development
database holds an admin account), `*.tsbuildinfo`, logs, ZIPs and `.git/`.

The employer CSV is included because the snapshot is a private backup needed for restoration.
It is not a redistribution, and the ZIP should not be uploaded publicly (see the
"Remaining actions" section).

### Snapshot verification (executed)

- ZIP integrity test passed. There are no `.env`, database, virtual-environment,
  `node_modules`, `.next`, cache, `.pyc` or log entries.
- The real `DJANGO_SECRET_KEY` value from your `.env` appears in no archived file (checked by
  value, not printed). Token and private-key patterns: none. Absolute home-directory paths: none.
- All expected key files are present: import engine and views, migration 0002, admin
  templates and CSS, optimizer, map component, lockfile, Postman collection, data files,
  environment examples.
- Extracted copy: `sha256sum -c SNAPSHOT-MANIFEST.txt` all OK; every file is identical to the
  working tree.
- **Restore test from the extracted ZIP:**
  - backend `pytest -q` 511 passed; Ruff check and format pass; `check` reports no issues;
    `makemigrations --check` reports no changes.
  - A fresh `.env` from `.env.example`, `migrate` and `import_fuel_prices` on a new database
    gave 8,151 rows read, 6,626 inserted, 620 Canadian rows skipped, 905 duplicates merged,
    6,228 town-level, 398 unresolved (27 ambiguous, 371 not found) and 0 rejected.
  - Frontend `tsc --noEmit`, ESLint and 7/7 Node tests pass using the existing dependencies.

## Verification results (this session)

| Check | Result | Where |
|---|---|---|
| `python manage.py check` | No issues | Container, byte-identical `backend/` (97 files, matching manifest hash with the Mac) |
| `makemigrations --check --dry-run` | No changes | Same |
| `pytest -q` | **511 passed** | Same, and again from the restored ZIP |
| `ruff check .` / `ruff format --check .` | Pass / 73 files formatted | Same |
| `npm run typecheck` (`tsc --noEmit`) | Pass | Linux VM on a copy of `frontend/` |
| `npm run lint` (`eslint .`) | Pass | Same |
| `npm test`, part 1: `node --test` | **7/7 pass** | Same |
| `npm test`, part 2: Vitest (29) | **Unverified this session** | Needs macOS-native `rollup` binaries; last passed in M8; no frontend source changes since |
| `npm run build` | **Unverified this session** | Needs macOS-native `swc`; last passed in M8 |
| Postman collection, 8 requests against live Django and OSRM | 8/8 expected statuses (200×5, 400, 422×2) | Your running server |

Frontend source is unchanged since M8: `git status` shows only `frontend/README.md` modified,
by this documentation task.

## Documentation work

| File | Change |
|---|---|
| `README.md` | Rewritten for a reviewer, in the requested 24-part order: requirement map, features, stack, architecture sketch, setup with verified commands, CORS for both origins, data provenance and how to supply the CSV, API summary, live example, optimizer explanation, purchases versus whole-trip cost, measured performance with OSRM latency separated, tests, admin, import, limitations, Postman, Loom, doc index |
| `docs/project-architecture-snapshot.md` | New: module-by-module inventory checked against the code (classes, functions, URLs, request flow, cache key, geolocation, admin import, frontend, error handling, tests per file) |
| `docs/api-contract.md` | Example replaced with the real live Dallas–Atlanta response (was a stand-in); health and route-only examples; caching, attribution and measured live timings |
| `frontend/README.md` | Opens `127.0.0.1:3000`; CORS guidance for both origins; fixed README anchor |
| `docs/loom-demo-script.md` | Both dashboard origins; table of VS Code files to show (all paths verified) |
| `docs/github-readiness.md` | New section on whether the employer CSV may be redistributed |
| `docs/submission-checklist.md` | CSV decision item |
| `docs/final-pre-submission-audit.md`, `docs/admin-fuel-import.md` | Optimizer complexity wording; Canadian-row wording |

All relative links in the 20+ Markdown files resolve (checked by script). Every command in the
README was checked against the repository: management commands and options, npm scripts,
requirements files and environment variables.

## Security findings

- No secrets in tracked or untracked files. `.env`, databases, virtual environments,
  `node_modules`, `.next` and `*.tsbuildinfo` are ignored (`git check-ignore` confirmed).
- The only key-like string is the documented insecure fallback used solely when `DEBUG` is on.
- Docs contain no credentials and no absolute local paths. The only absolute home paths are in
  ignored build or virtual-environment output.
- Third-party provenance is kept (`backend/data/reference/SOURCE.md`; OSRM/OSM attribution in
  API responses and on the map).
- **Employer CSV:** redistribution rights are undocumented. It has been tracked since commit
  `b830597`, so it is in the history. Options are in [github-readiness.md](github-readiness.md).
  This needs your decision before publishing.
- Dependency advisory scans (`pip-audit`, `npm audit`) were not run, because the advisory
  services are unreachable from the audit tools. Django 6.1.2 is the current security release.

## Remaining limitations (documented)

Approximate town-level station points; no verified access or detours; static prices; no fuel
reserve; `total_purchase_cost` excludes the starting tank (whole-trip cost needs a starting
price); public OSRM rate limits and availability; greedy practical-stop policy; SQLite and
local settings are not a production deployment.

## Git status after this task

Modified (tracked): `.env.example`, `README.md`, `backend/apps/fuel/{geolocation,importer,models}.py`,
`backend/config/{settings,test_settings,urls}.py`, `backend/requirements.txt`,
`docs/{api-contract,architecture,github-readiness,loom-demo-script,submission-checklist}.md`,
`frontend/README.md`.
Untracked: admin app files, `admin_import.py`, `station_import.py`, migration 0002,
`backend/static/`, `backend/templates/`, `tests/test_admin.py`, `tests/test_station_import.py`,
`docs/admin-enhancement.md`, `docs/admin-fuel-import.md`, `docs/final-pre-submission-audit.md`,
`docs/project-architecture-snapshot.md`, `docs/final-snapshot-report.md`.

This task changed **documentation only**. The backend tree manifest hash is unchanged
(`9e5657…`), there are no frontend source changes, and nothing is staged. The snapshot is outside
the repository.

## Remaining actions for you

1. Run `cd frontend && npm test && npm run build` on the Mac (Vitest and the build were not
   runnable here).
2. Decide on the employer CSV before making anything public.
3. Fix your local `.env`:
   `DJANGO_CORS_ALLOWED_ORIGINS=http://localhost:3000,http://127.0.0.1:3000`, then restart Django.
4. Review the README and these docs, then commit locally (not done by this task).
5. Publish, record the Loom video, and add both links to the README and checklist.

## Snapshot checksum

`routefuel-pre-github-2026-10-22.zip` — 2,213,148 bytes, 152 project files plus manifest and
restore notes. SHA-256:

```
593ff1ef76148da9ea1816030cc22f41291406f39cf5b7e87e206c16a7fa0885
```

Verified after a fresh extraction: manifest OK; 511 backend tests passed; Ruff, `check` and
migration checks clean; fresh migrate and CLI import reproduced 6,626 / 6,228 / 398;
frontend type-check, lint and Node tests pass. This section was added to the repository copy
after the ZIP was built, so the copy inside the ZIP ends before it.
