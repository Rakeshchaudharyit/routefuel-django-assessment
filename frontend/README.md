# RouteFuel dashboard · M5

Next.js App Router, React, strict TypeScript, Tailwind CSS, MapLibre GL JS and Lucide.
All API shapes come from [the v1 contract](../docs/api-contract.md).

## Run locally

Requires Node.js 20.9 or newer (verified with 22.23.2).

```sh
cd frontend
npm install
cp .env.example .env.local
npm run dev
```

Open http://localhost:3000. In another terminal, run the existing Django backend:

```sh
cd backend
../.venv/bin/python manage.py runserver
```

`NEXT_PUBLIC_API_BASE_URL` defaults to `http://127.0.0.1:8000`. It is public browser
configuration; never put private keys here. Django must allow the frontend's browser
origin in its existing `DJANGO_CORS_ALLOWED_ORIGINS` setting. The local `.env` used
for verification allows `http://localhost:3000`, so use that frontend URL.

## Checks

```sh
npm run typecheck
npm run lint
npm test
npm run build
npm start
```

The production build deliberately uses Next.js's supported Webpack option. Turbopack's
PostCSS worker fails to bind its internal port under this environment's sandbox.
The development server uses Turbopack. `package-lock.json` pins resolved versions.

## Structure and scope

- `src/app/`: dashboard route, API documentation and global design tokens/styles.
- `src/components/layout/`: responsive navigation and workspace shell.
- `src/components/route-planner/`: form validation, request lifecycle and result state.
- `src/components/map/`: browser-only MapLibre component and typed map adapter.
- `src/components/trip-summary/`: API totals with missing-value and whole-trip cost handling.
- `src/components/fuel-stops/`: reusable station cards with location accuracy.
- `src/hooks/`: abortable health checks on mount, manual refresh and every 60 seconds.
- `src/lib/api/`: typed health, route and optimizer clients; 30-second route deadline.
- `src/lib/utils/`: lossless decimal-string formatting and distance/time display.
- `src/types/`: documented requests, responses and error envelope.
- `tests/`: transport, deadline/cancellation, error and decimal precision checks.

M5 submits real optimization requests and presents returned summaries and stop cards.
It never seeds demo statistics or calculates fuel plans. The map shows a real CARTO
Positron basemap with OSM/CARTO attribution, pan/zoom and reset controls. No key is
required; internet access is required for tiles.

The reusable map adapter accepts geometry, endpoints, fuel stops, attribution and
marker selection callbacks. **The dashboard deliberately does not connect the API
result to that adapter yet:** API-driven drawing, selected-card synchronization and
station interaction are M6. Approximate marker halos are schematic, not geographic
uncertainty circles. No route coordinates or station locations are fabricated.

See [the M5 verification report](../docs/m5-frontend-report.md) for acceptance results
and limitations. M6 has not been started.
