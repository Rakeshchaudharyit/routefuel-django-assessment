# RouteFuel

A Django REST API that plans a driving route between two US locations and recommends where to
buy fuel so the trip costs as little as possible. Built as the backend assessment for the
Backend Django Engineer role at Spotter AI.

> **Status:** M0 (foundation) complete. Routing, fuel data and optimisation arrive in M1–M4 —
> see [docs/milestones.md](docs/milestones.md).

## Assessment requirements

The finished API will:

1. Accept start and finish locations within the USA.
2. Calculate a driving route between them.
3. Return route geometry suitable for a map.
4. Identify cost-effective fuel stops along the route.
5. Use the employer-provided fuel-price CSV.
6. Assume a maximum range of 500 miles.
7. Assume 10 miles per gallon.
8. Report the estimated total fuel expenditure.
9. Support multiple fuel stops on long trips.
10. Minimise external routing API calls.
11. Respond quickly.
12. Handle errors gracefully.

## Technology stack

| Layer | Choice |
|-------|--------|
| Language | Python 3.12+ (developed on 3.13) |
| Framework | Django 6.1, Django REST Framework 3.18 |
| Database | SQLite |
| HTTP client | httpx (routing provider, from M2) |
| Routing | OSRM (from M2) |
| Tests | pytest, pytest-django |
| Lint / format | Ruff |
| Frontend (M5+) | Next.js, React, TypeScript, Tailwind CSS, MapLibre GL JS |

## Local installation

```bash
git clone <repo-url> routefuel
cd routefuel
cp .env.example .env            # then edit DJANGO_SECRET_KEY

cd backend
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
python manage.py migrate
```

## Environment configuration

Settings are read from environment variables, or from `.env` at the repository root.
Real environment variables take precedence over `.env`.

| Variable | Default | Purpose |
|----------|---------|---------|
| `DJANGO_SECRET_KEY` | none — required when debug is off | Django cryptographic signing |
| `DJANGO_DEBUG` | `false` | Debug mode; enables the browsable API |
| `DJANGO_ALLOWED_HOSTS` | `localhost,127.0.0.1` | Comma-separated hosts |
| `DJANGO_CORS_ALLOWED_ORIGINS` | `http://localhost:3000` | Origins allowed to call `/api/*` |
| `ROUTING_BASE_URL` | `https://router.project-osrm.org` | OSRM-compatible routing server |
| `ROUTING_TIMEOUT` | `10` | Routing request timeout in seconds (must be > 0) |

Invalid values (e.g. `DJANGO_DEBUG=maybe`, `ROUTING_TIMEOUT=0`) fail fast at startup with a clear message.

## Running Django

```bash
cd backend
python manage.py check
python manage.py runserver
curl http://127.0.0.1:8000/api/v1/health/
# {"status":"ok","service":"routefuel-api"}
```

## Running tests and quality checks

```bash
cd backend
pytest                   # test suite (uses in-memory SQLite and fixed test settings)
ruff check .             # lint
ruff format --check .    # formatting
```

## API

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/health/` | Liveness check. No database or external calls. |

Errors use one envelope: `{"error": {"code": "...", "message": "...", "details": ...}}`.

## Project structure

```
routefuel/
├── backend/
│   ├── config/             settings, test settings, root URLs, WSGI/ASGI
│   ├── apps/
│   │   ├── core/           health endpoint, error envelope
│   │   ├── routing/        location resolution & OSRM (M2)
│   │   ├── fuel/           fuel CSV import & station queries (M1)
│   │   └── optimization/   fuel-stop optimiser (M3)
│   ├── tests/              pytest suite
│   ├── data/               fuel-price CSV goes here
│   ├── manage.py
│   ├── requirements.txt    runtime dependencies
│   ├── requirements-dev.txt
│   ├── pyproject.toml      Ruff configuration
│   └── pytest.ini
├── frontend/               Next.js dashboard (M5–M6)
├── docs/
│   ├── architecture.md
│   └── milestones.md
├── .env.example
└── README.md
```

## M0 acceptance criteria

1. Django starts successfully.
2. Dependencies are installed.
3. Django REST Framework works.
4. SQLite migrations succeed.
5. `/api/v1/health/` returns HTTP 200.
6. Automated tests pass.
7. Django system checks pass.
8. Ruff checks pass.
9. README exists.
10. Architecture documentation exists.
11. Environment configuration is documented.
12. Git is initialised.
13. No secrets or generated files are committed.

See [docs/architecture.md](docs/architecture.md) for design decisions and the technical
considerations planned for later milestones.
