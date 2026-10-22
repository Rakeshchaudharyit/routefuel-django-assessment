# Final submission checklist

Updated: 22 October 2026. **Local preparation is complete; publication and submission are pending.**
M7 is preserved in local commit `d44d473`; M8 preparation is committed separately. Nothing has
been pushed or uploaded, and no Loom recording has been made by this task.

## Verified locally

- [x] Backend tests: **416 passed** in M8 (4.22 seconds).
- [x] Django system check, migration drift check, Ruff lint and format checks pass.
- [x] Frontend tests: **36 passed** (seven Node tests + 29 Vitest tests).
- [x] TypeScript, ESLint and production webpack build pass.
- [x] Real OSRM routing verified again through `manage.py verify_routing`: Dallas–Atlanta
  778.8 miles, three stops, $78.19 purchases; fresh request one provider call, cached repeat zero.
- [x] Live HTTP smoke collection: eight expected statuses pass, including New York–Los Angeles
  (2,810.37 miles / 17 stops / $698.65) and both 422 examples.
- [x] Fuel optimization verified against independent reference DP; raw plans replay-check.
- [x] Dashboard functional: real desktop/mobile map, selection, cost and error checks in M7;
  current M8 tests/build pass. See [QA report](m7-final-qa-report.md).
- [x] Fresh disposable SQLite database: migrations, 6,626-station import, 6,228 city coordinates
  and idempotent second import pass. Existing development database was not replaced.
- [x] README setup, API usage, data import, costs, routing and limitations reviewed and updated.
- [x] Postman collection and configurable local environment included; import/demo instructions written.
- [x] Loom script prepared for the required segments, with a 4:50 target and approximately
  393 spoken words. Actual duration remains to be measured during recording.
- [x] No exposed credentials found by manual example/config review and targeted token/private-key
  scans of tracked files and 181 reachable historical blobs. This is not an exhaustive guarantee.
- [x] Generated databases, sidecars, real `.env` files, dependencies, builds and virtual
  environments are ignored and untracked. Public environment examples are intentionally tracked.
- [x] Required CSV/reference files retained; both reference SHA-256 checksums match source notes.
- [x] Machine-specific project paths removed from current documentation; no screenshots or
  videos are tracked. Historical commits were not rewritten.
- [x] Known limitations documented: approximate stations, unverified access/detours, no reserve,
  static prices, rounding, greedy practical-stop policy and minor popup clipping.

## Manual review and publication — still pending

- [ ] Review the local M7 and M8 commits and approve public publication.
- [ ] Execute the collection's JavaScript assertions in native Postman or Newman. The terminal
  runner checks HTTP statuses only; it does not execute those assertions.
- [ ] Create public GitHub repository `routefuel-django-assessment` after review.
- [ ] Replace the local `origin` with the actual GitHub remote and push `main` manually.
- [ ] Verify the repository is accessible while signed out, including data and Postman files.
- [ ] Clone the published repository into a new directory and follow the README installation.
- [ ] Record Loom manually and watch it end to end.
- [ ] Confirm **actual video duration is below five minutes** (script target: 4:50).
- [ ] Verify readable text, audible explanation and no secrets in the recording.
- [ ] Verify Loom playback/sharing while signed out or with reviewer-level access.
- [ ] Add the actual GitHub and Loom links below, then send the assessment submission manually.

GitHub repository: **Pending — not created**

Loom video: **Pending — not recorded**

Publication instructions: [GitHub readiness](github-readiness.md). Recording outline:
[Loom script](loom-demo-script.md). API demonstration: [Postman guide](postman/README.md).

## Outstanding qualifications

Dependency advisory scanning timed out during M7; vulnerability status remains unverified.
Live routing and map tiles require external services and should be rechecked on the recording
network. These are disclosed qualifications, not claims of failed application checks. Exact
station geocoding, road access and reserve-fuel modeling were not added during submission prep.
