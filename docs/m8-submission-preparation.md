# M8 — Local submission preparation

Date: 22 October 2026. No external publication, upload, recording or submission performed.

## Preservation and repository review

Reviewed the M7 application changes, regressions, live evidence and documentation, then
preserved them in **`d44d473`**, a separate local commit following M6 `49b4c19`. The working
optimizer was not modified. The previously untracked `frontend/.env.example` contains only
the public local API URL; it is now documented and included in the M8 preparation commit.

Reviewed repository inventory, requirements, package metadata/lock, configuration examples,
ignore rules, CSV/reference sources, Postman bodies/assertions and README commands. No
tracked databases, build outputs, dependency directories, virtual environments, screenshots
or secret environment files were found. Required inputs are retained: the largest file is
the 5.96 MB Census gazetteer, followed by the 1.14 MB state boundary file and 0.58 MB supplied
CSV. Both reference checksums match their source documentation.

Targeted scans for private keys, common GitHub/OpenAI/AWS credential patterns and credentialed
HTTP URLs found no matches in tracked files or 181 reachable historical blobs. Environment
examples contain placeholders or public URLs; tests use explicit fixed test settings. This
review is not an exhaustive secret-scanner or dependency-vulnerability certification.
Machine-specific repository paths in M5–M7 reports were replaced with `<repository-root>`;
prior Git history was retained. The existing `origin` remains a local filesystem remote and
must be replaced manually after approval; it was not changed during this preparation.

## Submission-only changes

- `.gitignore`: ignore SQLite WAL/SHM sidecars in addition to the database/journal.
- `README.md`: consolidate setup, prerequisites, API examples, costs, tests, routing, caching,
  practical-stop behavior and known limitations; replace old stand-in response with an
  explicitly abridged live example; link submission material.
- `frontend/README.md`, `frontend/.env.example`: use locked `npm ci` setup and explain public
  API configuration, backend prerequisites and local environment override.
- `docs/m5-frontend-report.md`, `docs/m6-integration-report.md`, `docs/m7-final-qa-report.md`:
  remove machine-specific repository paths; record the subsequent M7 preservation commit.
- `docs/milestones.md`: distinguish locally prepared M8 from pending publication/submission.
- `docs/postman/README.md`: import, environment, delay, expected statuses and demo instructions.
- `docs/postman/run_collection.py`: space requests by 1.1 seconds to respect light public
  routing usage; tested against the real API after this change.
- `docs/loom-demo-script.md`: 393 spoken words with actions mapped to every requested segment,
  0:00–4:50. Actual recording duration must be checked manually.
- `docs/github-readiness.md`: public repository name and exact manual create/connect/push steps.
- `docs/submission-checklist.md`: checked local evidence and unchecked publication/video tasks.
- This preparation report.

## Executed checks

| Check | M8 result |
|---|---|
| `python manage.py check` | No issues |
| `python manage.py makemigrations --check --dry-run` | No changes detected |
| `pytest -q` | 416 passed in 4.22 s |
| `ruff check .` / `ruff format --check .` in backend | Pass; 65 files formatted |
| `npm test` | 7 Node + 29 Vitest = 36 passed |
| `npm run typecheck` | Pass |
| `npm run lint` | Pass |
| `npm run build` | Pass; existing webpack build command |
| Ruff lint/format for changed Postman runner | Pass using backend Ruff config |
| `python manage.py verify_routing` | All live checks pass |
| Updated terminal collection runner | 8/8 expected HTTP statuses pass |
| Fresh disposable database | Migrations/import/geolocation/reimport pass |

Live Dallas–Atlanta: 778.8 miles, 8,177 full geometry points, three stops, $78.19 purchases.
The explicit uncached API request made one provider call; repeat and optimization used the
cache. Direct provider call measured 773 ms; the uncached in-process API check measured
475 ms, cached repeat 1 ms and optimization 14 ms in this run. These are separate calls,
not percentiles or a decomposition of a single request.

The updated HTTP runner reproduced New York–Los Angeles 2,810.37 miles, 17 stops, $698.65;
custom starting-fuel request 200; validation 400; unreachable and infeasible 422. Native
Postman/Newman JavaScript assertions were reviewed but not executed here. Real dashboard
browser evidence is from M7; M8 reran frontend checks without changing application behavior.
The temporary Django server was stopped after verification.

## Readiness and remaining steps

Local code, README, collection, script and publication instructions are ready for review.
M8 publication is not complete: the user must approve and create/push the public repository,
record Loom, verify both links and submit them. No remote repository or Loom URL is invented.
Fresh external clone installation and native Postman assertions remain manual checklist items.

The main technical qualification remains town-level station coordinates and unverified pump
access/detours. The model has static prices and no reserve; the practical policy is greedy,
rounded display fuel is not an exact physical replay, and an open map popup can clip after
fitting the full route. Dependency advisory scanning remains unverified after M7's timeout.
These limits are retained in README and the recording script; no new application features
or infrastructure were added.
