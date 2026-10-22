# Deploying the RouteFuel API to Render with Neon PostgreSQL

Production layout: Django API on Render (Root Directory `backend`), Neon PostgreSQL, and the
Next.js dashboard on Hostinger at `https://routefuel.cortexaautomation.pro`.

## Render environment variables

Set these in the Render dashboard (Environment). Never commit them.

| Variable | Value |
|---|---|
| `DATABASE_URL` | Neon connection string from the Neon console, e.g. `postgresql://USER:PASSWORD@HOST/neondb?sslmode=require` |
| `DJANGO_SECRET_KEY` | A new random key: `python -c "from django.core.management.utils import get_random_secret_key as k; print(k())"` |
| `DJANGO_DEBUG` | `false` |
| `DJANGO_ALLOWED_HOSTS` | `routefuel-api.onrender.com` |
| `DJANGO_CORS_ALLOWED_ORIGINS` | `https://routefuel.cortexaautomation.pro` |
| `ROUTEFUEL_DASHBOARD_URL` | `https://routefuel.cortexaautomation.pro` |

Optional, defaults are fine: `ROUTING_BASE_URL`, `ROUTING_TIMEOUT`, `ROUTING_USER_AGENT`,
`ROUTE_CACHE_TTL`, `FUEL_CORRIDOR_MILES`, `DJANGO_SECURE_COOKIES` (defaults to true when
`DJANGO_DEBUG=false`). Render sets `RENDER=true` itself; with it, the app refuses to start or
build without `DATABASE_URL` instead of using a throwaway SQLite file.

## Build and start commands

Use two ASCII hyphens (`--`), not a typographic dash.

Build command:

```
pip install -r requirements.txt && python manage.py collectstatic --noinput && python manage.py migrate --noinput
```

Start command:

```
gunicorn config.wsgi:application --bind 0.0.0.0:$PORT
```

## Migrations

Render Free has no pre-deploy command and no shell, so migrations run at the end of the build.
This is safe for this project:

* The build has the same environment variables as the running service, so `migrate` targets
  Neon. Without `DATABASE_URL` the build fails; it can never migrate SQLite on Render.
* If `migrate` fails, the build fails and Render keeps the previous deploy live.
* `migrate` only applies migration files in the repository; rerunning it is a no-op
  ("No migrations to apply"). Do not run `flush`, `reset_db` or hand-written `DROP` statements.

On a paid instance, move `python manage.py migrate --noinput` from the build command to the
Pre-Deploy Command instead.

## One-off tasks from your own computer (superuser, station import)

Render Free has no shell, so run one-off commands locally against Neon. The connection string
stays in the shell's memory only: it is not echoed, not saved to shell history and not written
to `.env`.

```
cd backend
source ../.venv/bin/activate
pip install -r requirements.txt          # installs psycopg, dj-database-url, whitenoise
read -rs DATABASE_URL && export DATABASE_URL   # paste the Neon URL, press Enter (nothing is shown)
python manage.py migrate --check         # exit 0 = Neon is fully migrated (deploy first)
```

### Create the first superuser

```
python manage.py createsuperuser         # prompts; the password is typed hidden
```

Use a long unique password (at least 12 characters; the validators reject weak ones). Sign in at
`https://routefuel-api.onrender.com/admin/`.

### Import the employer fuel-station dataset

The CSV and the offline gazetteer are tracked in Git under `backend/data/`, so they are present
in the Render build and in your checkout. Preview first, then import:

```
python manage.py import_fuel_prices --dry-run
python manage.py import_fuel_prices
```

Expected first import: 8,151 CSV rows, 620 non-US rows skipped, 905 duplicate rows merged,
**6,626 stations inserted**, then geolocation with **6,228 city-level** and **398 unresolved**
(27 ambiguous, 371 not found). Unresolved stations keep empty coordinates; nothing is invented.

The import is idempotent: rerunning it reports `Inserted 0, Updated 0, Unchanged 6626`, and
geolocation only reconsiders the 398 unresolved stations without changing them. Stations that
exist in the database but not in the file are kept, never deleted.

When finished:

```
unset DATABASE_URL
```

Staff can also upload the same CSV through Admin → Fuel stations → **Import Fuel Stations**
(see `admin-fuel-import.md`).

## Frontend

The Hostinger build must set `NEXT_PUBLIC_API_BASE_URL=https://routefuel-api.onrender.com`.
`NEXT_PUBLIC_*` values are compiled into the bundle, so rebuild the frontend after changing it.

## Smoke test after deploy

* `https://routefuel-api.onrender.com/api/v1/health/` returns `{"status":"ok",...}`.
* `/admin/` login page shows the RouteFuel styling (CSS/JS served by WhiteNoise).
* Signing in works (no CSRF "Origin checking failed" error) and Fuel stations lists 6,626 rows.
* The dashboard at `https://routefuel.cortexaautomation.pro` can plan a route.

A free instance sleeps after 15 minutes without traffic; the first request afterwards takes
about a minute.
