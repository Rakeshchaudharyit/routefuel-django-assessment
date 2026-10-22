# Django administration — post-M8-preparation enhancement

Implemented and verified locally on 22 October 2026. The public routing API, optimizer,
CSV importer, OSRM integration and Next.js application are unchanged. No dependencies added,
no administrator created in the development database, and no push or publication performed.

## Behavior and files

- `backend/config/urls.py`: `GET /` returns a temporary 302 redirect to `/admin/`; native admin
  URLs, RouteFuel header, RouteFuel Administration title and Operations Administration index.
- `backend/config/settings.py`: admin, sessions, messages, authentication/CSRF middleware,
  template context processors, static directories, password validators and session settings.
- `backend/config/test_settings.py`: deterministic secure-cookie settings for regression tests.
- `backend/apps/fuel/admin.py`: FuelStation registration, useful columns, search/filters,
  field groups, native permissions and read-only created/updated timestamps.
- `backend/templates/admin/base_site.html`: native admin layout with RouteFuel branding/styles.
- `backend/templates/admin/login.html`: responsive sign-in form with labels, CSRF, generic
  errors and a progressive password visibility control.
- `backend/static/routefuel/admin.css`, `backend/static/routefuel/login.js`: navy/teal theme,
  spacing, restrained borders/shadows, responsive card, visible focus and keyboard toggle.
- `.env.example`, `README.md`, `docs/architecture.md`: setup and security documentation.
- `backend/tests/test_admin.py`: 19 added admin/security regression cases.
- This report.

Django's built-in admin/session migrations were applied locally. There are no new project
model migrations and no FuelStation schema changes. The ignored development SQLite database
was not added to Git. Existing accounts, if any, are not modified.

## Authentication and security

Django's native admin login form/view, default password hashers, database-backed sessions and
model permissions handle access. Active staff status is required even for a direct model URL;
view/add/change/delete permissions govern the operations available. Standard Django admin
user/group management remains available to authorized users. No custom password scheme or
credential default is introduced.

The custom login template presents one generic staff-credential error for invalid attempts;
it does not expose whether a username exists. Required field errors remain accessible.
Django validates safe redirect targets, rotates session/CSRF state at login, enforces CSRF on
admin forms, and invalidates the session on POST logout. GET logout is not allowed.

The session cookie is HttpOnly, SameSite=Lax, scoped to `/admin/`, with an eight-hour age.
Session and CSRF cookies default to Secure when DEBUG is off. `DJANGO_SECURE_COOKIES` allows
an explicit local HTTP exception; production HTTPS should leave this enabled. DRF retains
empty authentication classes and AllowAny; admin sessions do not authenticate the public API.
Public JSON POSTs continue to work without admin CSRF tokens, as before.

Native password validators enforce minimum length 12, similarity, common-password and numeric
checks in supported forms/commands. Administrators create accounts through `createsuperuser`
or authorized user administration, change their password through the native screen, and can
recover accounts through an authorized operator's `changepassword` command. No email reset
flow is exposed or configured. Reference: [Django authentication documentation](https://docs.djangoproject.com/en/6.1/topics/auth/default/)
and [cookie settings](https://docs.djangoproject.com/en/6.1/ref/settings/).

## FuelStation operations

Columns: name, OPIS ID, city, state, retail price, geolocation accuracy and boolean geolocated
status. Search: name, exact OPIS ID, city, address. Filters: state, accuracy, source. Native
pagination shows 50 rows per page. View-only staff can inspect records but cannot save/add/
delete; change permission allows valid edits, not deletion without the delete permission.
Model constraints apply to forms and native history records changes.

The location fieldset explicitly describes town approximations. Editing is permission-gated
but can affect route recommendations; CSV import continues to use its existing reconciliation
rules. Importer and optimization code were not modified.

## Executed verification

| Check | Result |
|---|---|
| Django `check` | No issues |
| `makemigrations --check --dry-run` | No changes detected |
| Full backend pytest | **435 passed in 8.42 seconds** (416 preserved + 19 added) |
| Ruff check | Pass |
| Ruff format check | Pass; 67 backend files formatted |
| `collectstatic --dry-run --noinput` | Pass |
| Real HTTP Postman stdlib runner against isolated admin-enabled server | **8/8 expected statuses pass** |

New tests cover root redirect, anonymous protection, native branding/CSRF markup, valid staff
login and hashed passwords/cookies, identical known/unknown invalid-credential errors, inactive
and nonstaff denial, logout method/session invalidation, login/logout CSRF, external-next
rejection, read/change/delete permission boundaries, password validators, HTTPS cookie flags,
public health/JSON POST equivalence with/without an admin session, and edit-form CSRF.
Existing route/optimization contracts and all prior regression tests pass unchanged.

The HTTP smoke run reproduced Dallas–Atlanta 778.8 miles / three stops / $78.19, New York–Los
Angeles 2,810.37 miles / 17 stops / $698.65, the custom vehicle success, validation 400 and
unreachable/infeasible 422 results. Successful routes used existing real provider cache entries;
the unreachable request contacted real OSRM. This was not a fresh full routing benchmark.
The runner checks statuses, not Postman's JavaScript assertions.

### Browser checks actually performed

Tested a real Django server on loopback port 8001 against a disposable copy of the station
database, since port 8000 was already occupied. Used one randomly credentialed, temporary
staff account with view-only FuelStation permission. The development database received no
QA account. Temporary server, credential file and copied database were removed after testing.

Verified root → admin → login navigation, generic invalid-login feedback, password show/hide
and Enter activation, successful staff login, branded index, station list, OPIS search 60540
returning one station, native POST logout, and redirect back to login after logout. Verified
1440 px desktop and 390 px mobile layouts; mobile client/scroll widths both measured 390,
and Tab moved from username to password. Captured desktop/mobile screenshots outside Git.
Native forms and navigation work without the visibility script; no React code is involved.
No automated accessibility certification, other browser engine test or HTTPS deployment test
is claimed. The Next.js suite was not rerun for this backend-only enhancement; its application
files and API contract remain unchanged.

## Manual setup and remaining qualifications

With the virtual environment active, from `backend/`:

```bash
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver 127.0.0.1:8000
```

Provide your own username, email and password, then visit `http://127.0.0.1:8000/admin/`.
Use the native Log out button; create least-privilege staff/group assignments for routine
station management. If a server was running before this change, restart it to load the new
settings and routes. No default credentials are provided.

For deployment, configure HTTPS and a trusted proxy correctly, keep secure cookies on, set
production hosts/secret/DEBUG, and serve collected static files. Built-in Django admin does
not include MFA or login-attempt rate limiting; apply deployment access controls as needed.
Account creation, email recovery policy and an actual HTTPS/proxy deployment need operator
configuration. Town geolocation and other routing limitations from M7 still apply.

Changes remain uncommitted for review on top of M8 commit `8226559`. No Git history, authorship
or remote was changed. Ready for manual administrator creation and final review.

## Follow-up: fuel-station CSV/Excel import

Added afterwards on 22 October 2026; the admin styling, authentication and settings above were
not changed. Full behavior, rules and measurements: [admin fuel-station import](admin-fuel-import.md).

- **Import Fuel Stations** button on the station list (`change_list.html` override) and
  screens at `/admin/fuel/fuelstation/import/`: upload, preview, confirm, results, XLSX/CSV
  templates and CSV error report. Styling reuses the workspace tokens in a separate
  `static/routefuel/station-import.css`; `station-import.js` only prevents double submission.
- Files: `apps/fuel/station_import.py` (parsing, validation, planning, apply),
  `apps/fuel/admin_import.py` (admin views mixed into `FuelStationAdmin`), templates under
  `templates/admin/fuel/fuelstation/`, model `StationImport` with migration
  `fuel/0002_stationimport`, `tests/test_station_import.py` (71 tests).
- Small shared changes: three new reason codes in `importer.Reason`, and an optional
  `opis_ids` argument on `geolocate_stations` so only imported stations are geolocated.
  Existing CLI behavior is unchanged.
- **Changes to the statements above:** this follow-up adds one dependency (`openpyxl`) and
  one project migration. Run `pip install -r backend/requirements.txt` and
  `python manage.py migrate`, then restart the server.

Verification (container copy of the project, Python 3.13): `manage.py check` no issues;
`makemigrations --check` no changes; **511 passed** (440 existing + 71 new); Ruff check and
format pass. Headless Chromium against an isolated server on a copy of the station database
with a temporary QA superuser (both deleted afterwards): login, import button, template
download, unsupported-file error, preview counts and current → new values, error report,
double-click confirm (one POST), results, station list, repeat upload (nothing to import),
full employer CSV preview, logout, and a 390 px layout without horizontal page scroll.

