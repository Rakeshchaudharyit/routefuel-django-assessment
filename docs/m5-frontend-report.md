# M5 frontend report

Verified 21 October 2026. M5 only; M6 has not been started.

1. **Working directory:** `<repository-root>`, existing repository.
2. **Git status:** initially clean at `9a0b155` (M4). Final changes are the modified
   frontend README, new frontend files and this report. No backend source or API contract
   changes; no commits, history edits or pushes.
3. **Files created or modified:**
   - Modified `frontend/README.md`.
   - Added `frontend/package.json`, `package-lock.json`, `tsconfig.json`, `next.config.ts`,
     `postcss.config.mjs`, `eslint.config.mjs`, `.gitignore`, `.env.example`.
   - Next.js generated `frontend/AGENTS.md` with its local agent guidance.
   - Added `frontend/src/app/{layout.tsx,page.tsx,globals.css,api-documentation/page.tsx}`.
   - Added `frontend/src/components/layout/app-shell.tsx`.
   - Added `frontend/src/components/route-planner/{dashboard.tsx,route-form.tsx}`.
   - Added `frontend/src/components/map/route-map.tsx`.
   - Added `frontend/src/components/trip-summary/trip-summary.tsx`.
   - Added `frontend/src/components/fuel-stops/fuel-stops.tsx`.
   - Added `frontend/src/hooks/use-health.ts`, `frontend/src/lib/api/client.ts`,
     `frontend/src/lib/utils/format.ts`, `frontend/src/types/api.ts`.
   - Added `frontend/tests/api-client.test.mjs` and this report.
4. **Architecture:** Next.js App Router; server root layout; client dashboard and form;
   lazy browser-only MapLibre; reusable summaries and station cards; typed transport and
   health hook. Strict TypeScript. Tank capacity is calculated only for input validation;
   all fuel planning and cost calculations remain in Django.
5. **Design decisions:** off-white workspace, navy navigation, restrained teal controls,
   subtle borders, compact panels and consistent typography. Fuel Analysis scrolls to
   the summary; API Documentation opens a useful local reference.
6. **Components completed:** responsive shell, connection status/refresh, route form,
   swap action, advanced vehicle settings, validation, initial/loading/error/result states,
   map panel, trip summary, reusable fuel-stop cards and API documentation. Includes proper
   labels, error associations, live announcements, visible focus, skip link and reduced motion.
7. **API integration:** reviewed the API contract, Postman collection/runner, README and
   architecture before implementation. Typed clients cover GET `/api/v1/health/`, POST
   `/api/v1/routes/` and POST `/api/v1/routes/optimize/`. Uses documented fields only,
   simplified geometry requests, 30-second route and 5-second health deadlines, abort cleanup,
   error envelopes and network errors. No keystroke requests; submission is disabled while
   pending, with a 1.1-second repeat guard. Money stays as decimal strings. Missing data uses
   an em dash; whole-trip cost follows its status/cost_note. Health connection verified against
   real Django from `http://localhost:3000`: the existing local CORS configuration permits
   that origin but not `http://127.0.0.1:3000`. No backend settings were changed.
8. **Map foundation:** CARTO Positron through MapLibre, with OSM/CARTO attribution, zoom,
   pan, US bounds reset and failure/retry UI. Typed props support geometry, start/destination,
   station markers, fit bounds, attribution and marker-selection callback. Approximate
   markers have a schematic halo and explicit town-location label. API-to-map wiring,
   geographic uncertainty circles and card selection synchronization remain M6. No invented
   route or station coordinates.
9. **Responsive verification:** visually inspected 1440×1000 desktop, 768×1024 tablet and
   390×844 mobile. Tablet stacks the workspace above the summary pair; mobile stacks panels
   and collapses navigation. DOM measurements showed no horizontal overflow on tablet/mobile.
10. **TypeScript:** `npm run typecheck` passes with strict mode enabled.
11. **ESLint:** `npm run lint` passes without errors or warnings.
12. **Production build:** `npm run build` passes; outputs `/`, `/api-documentation` and the
    framework not-found route. Uses supported `next build --webpack` because Turbopack's
    CSS worker could not bind its internal port in this environment. Installation completed;
    lockfile included. Resolved stack: Next 16.4.2, React 19.3.1, TypeScript 5.9.3,
    Tailwind 4.3.3, MapLibre 5.24.0 and Lucide 0.468.0.
13. **Browser testing and unit tests:**
    - Local frontend returned HTTP 200; basemap and attribution rendered.
    - Verified connected/disconnected health states, empty-form validation, swap, advanced
      settings, mobile navigation, map reset, Fuel Analysis anchor and API documentation.
    - Default Dallas–Atlanta returned the real `no_feasible_fuel_plan` response, displayed
      with its API details. The local data provided no usable stops for that request;
      no backend data import or modification was performed.
    - With 1,000-mile range, 10 MPG, 100 starting gallons and $3.199 starting price, real
      Django returned a successful cached Dallas–Atlanta plan: 778.8 mi, 77.880 gal consumed,
      zero stops, $0.00 purchases and $249.14 whole-trip cost. The UI displayed these values.
      This verifies browser integration, not live OSRM or the provenance of the existing cache.
    - Found and fixed map cleanup on navigation; successfully repeated planner-to-documentation
      navigation. Added Next.js's smooth-scroll attribute to resolve its console warning.
      Final navigation checks showed no new runtime errors.
    - `npm test`: 7 passing tests for decimal precision, exact optimizer request, field errors,
      network failure, health service identity, timeout and caller cancellation. Test doubles
      exist only in unit tests; no fake responses or statistics are used by the application.
14. **Known limitations:** live OSRM remains unverified as documented in M4. Non-empty stop
    cards and map data props were not exercised with a real multi-stop browser response.
    Tiles need internet. The form currently accepts city/state strings; coordinate objects
    and stop-policy settings are supported by API types but have no form controls. Health
    means liveness, not provider/data readiness. Fuel prices are a static dataset; station
    coordinates are approximate town points and road access is unverified. Loading logic
    is implemented, but cached requests complete too quickly for sustained visual inspection.
15. **M5 acceptance checklist:**

    | # | Criterion | Result |
    |---|-----------|--------|
    | 1 | Next.js frontend | Pass |
    | 2 | Tailwind CSS | Pass |
    | 3 | Strict TypeScript | Pass |
    | 4 | Dashboard layout | Pass |
    | 5 | Route form | Pass |
    | 6 | Map foundation | Pass |
    | 7 | Trip summary | Pass |
    | 8 | Fuel-stop components | Pass |
    | 9 | Typed Django client | Pass |
    | 10 | Health integration | Pass |
    | 11 | Responsive layouts | Pass |
    | 12 | Loading/error states | Implemented; errors browser-tested |
    | 13 | ESLint | Pass |
    | 14 | TypeScript checks | Pass |
    | 15 | Production build | Pass |

16. **M6 readiness:** ready for API-to-map wiring, linked selection, geographic uncertainty
    visualization and multi-stop end-to-end verification. M6 has not been begun. No deployment
    or GitHub push performed. Preview servers were temporary verification processes; restart
    using the frontend README commands.
