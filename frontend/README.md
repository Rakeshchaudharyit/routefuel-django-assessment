# RouteFuel dashboard · M6

Next.js App Router, React, strict TypeScript, Tailwind CSS, MapLibre GL JS and Lucide.
The [v1 API contract](../docs/api-contract.md) is the source of truth.

## Run locally

Requires Node.js 20.9+ (M6 checks ran with 20.20.2).

```sh
cd frontend
npm install
npm run dev
```

Open http://localhost:3000. In another terminal, start the existing backend:

```sh
cd backend
../.venv/bin/python manage.py migrate
../.venv/bin/python manage.py import_fuel_prices
../.venv/bin/python manage.py runserver
```

The import is idempotent and loads the supplied CSV plus offline town-level coordinates.
A healthy server with an empty station database cannot plan routes requiring fuel purchases.
M6 verification found an empty local database and populated it with this existing command;
no backend source or API contracts were modified.

`NEXT_PUBLIC_API_BASE_URL` defaults to `http://127.0.0.1:8000`. Set it in the environment
before starting/building Next.js if needed. It is public configuration, never a place for
private keys. Django must allow the browser origin in `DJANGO_CORS_ALLOWED_ORIGINS`.
The current local configuration allows `http://localhost:3000`.

## Verify before the demonstration

```sh
cd backend
../.venv/bin/python manage.py verify_routing
```

This command contacts the real OSRM provider, verifies a fresh route and cache reuse,
and requests a fuel plan. It passed on this machine on 21 October 2026 after importing
station data. Live Dallas–Atlanta and New York–Los Angeles were also verified over HTTP
and in the dashboard. See [the M6 integration report](../docs/m6-integration-report.md).
The historical M4 connectivity block no longer reproduces on this machine. Re-run the
command on the machine/network used for Loom rather than relying on a cached route.

## Checks

```sh
npm run typecheck
npm run lint
npm test
npm run build
npm start
```

`npm test` runs all seven preserved M5 transport/formatting tests, followed by deterministic
Vitest/React Testing Library tests in jsdom. MapLibre is mocked only inside tests. The fixture
under `tests/fixtures/` combines documented example route/station data; its abridged geometry
is a test fixture, not a live routing result. No fixtures are imported by the application.

The build uses `next build --webpack` because Turbopack's PostCSS worker cannot bind its
internal port in the sandbox. Development uses Turbopack. Resolved dependencies are locked.

## Architecture and behavior

- `src/app/`: dashboard, API documentation and global styles; M5 layout preserved.
- `components/route-planner/`: validated form and request/selection lifecycle. Optional
  starting-fuel price and minimum savings per stop follow the documented contract.
- `components/map/route-map.tsx`: browser-only map lifecycle, resize handling and controls.
- `components/map/route-layer.ts`: one reusable route source, endpoint/station markers,
  geographic uncertainty areas, text-safe popups, attribution and selected station focus.
- `components/fuel-stops/`: station cards with keyboard-accessible selection and accuracy.
- `components/trip-summary/`: API totals, remaining fuel and separate stop/whole-trip costs.
- `hooks/use-health.ts`: abortable health checks on mount, refresh and every 60 seconds.
- `lib/api/`: typed transport plus runtime validation before rendering successful payloads.
- `lib/utils/`: lossless decimal formatting and duration/distance display.
- `types/`: exact documented wire types; no backend optimization is duplicated in React.

Requests happen only on submit. Pending submissions are disabled; deliberate rapid follow-ups
are queued to respect a 1.1-second request interval, with loading feedback and abort cleanup.
The last valid map, summary and stops stay visible while a new request runs or fails; a banner
identifies those results as the previous plan. Malformed/missing geometry is rejected before
MapLibre receives it. Zero-stop plans are successful results.

Map geometry is requested as `simplified` and passed through unchanged. Distances, station
mile markers and fuel totals always come from Django. Selection updates marker/card styles,
popup details and camera without rebuilding sources or markers. New successful plans update
the existing source and remove old markers. Resizing refits the complete route. Desktop/tablet
station lists scroll internally; mobile cards stack naturally. Native buttons support keyboard
activation and visible focus.

CARTO Positron tiles require internet and no private key. OSM/CARTO and API routing attribution
remain visible. Station coordinates are approximate Census town points; dashed uncertainty
areas use the API's town-size estimate, not a verified pump position, road detour or guaranteed
error boundary. Confirm actual road access before departure. Fuel prices are a static snapshot.

M7 has not been started. Historical M5 details remain in [its report](../docs/m5-frontend-report.md).
