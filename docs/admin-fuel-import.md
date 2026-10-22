# Admin fuel-station import (CSV / Excel)

Staff can add and update fuel stations from a spreadsheet inside the Django admin. Every
upload is validated and previewed first; nothing changes until the administrator confirms.
The public API, route optimizer, OSRM integration and the `import_fuel_prices` command are
unchanged.

## Access and permissions

1. Sign in at `http://127.0.0.1:8000/admin/`.
2. Open **Fuel stations** and click **Import Fuel Stations** (next to *Add fuel station*), or
   go to `/admin/fuel/fuelstation/import/`.

| Action | Requires |
|---|---|
| Open the import screen, download templates, upload and preview | active staff + `fuel.add_fuelstation` **or** `fuel.change_fuelstation` |
| Confirm a preview that creates stations | `fuel.add_fuelstation` |
| Confirm a preview that updates stations | `fuel.change_fuelstation` |
| View a preview, its results or its error report | the staff user who uploaded it |

Permissions are checked again on confirmation. All screens use Django's admin login, session,
CSRF protection and `no-store` caching; data changes only on CSRF-protected POST requests.
There is no public upload endpoint.

## Files

- **Formats:** `.csv` (UTF-8, comma-separated; a BOM is fine) and `.xlsx`.
- **Limits:** 5 MB, 20,000 data rows, 30 columns. The full employer CSV (8,151 rows, 0.6 MB)
  fits comfortably.
- The real content is checked, not just the extension. Rejected: `.xls`, `.xlsm`/macro
  workbooks (also a `.xlsx` containing `vbaProject.bin`), password-protected workbooks,
  binary data named `.csv`, non-UTF-8 CSVs, damaged archives, and archives that expand to
  more than 64 MB.
- XLSX is read with `openpyxl` in read-only mode. Formulas are never evaluated: a formula,
  error value (`#DIV/0!`), date or TRUE/FALSE cell rejects that row with a reason. If a
  workbook has a sheet named **Stations**, only that sheet is read; otherwise the first sheet.
- Uploaded files are not saved. Only the validated, normalized rows are stored in the
  database (`fuel_stationimport`) to make the confirmation repeatable and auditable.

## Template and columns

**Download Excel template** gives `fuel-stations-template.xlsx` with three sheets:
*Stations* (header only — fill this in), *Example* (two clearly marked sample rows, never
imported) and *Field guide*. **CSV header** downloads the same header as a CSV. Headers are
identical to the employer CSV, so that file can be uploaded as-is. Header matching ignores
case and extra spaces.

| Column | New station | Existing station | Rules |
|---|---|---|---|
| OPIS Truckstop ID | Required | Required | Positive integer; the only matching key |
| Truckstop Name | Required | Optional | ≤ 255 characters |
| Address | Optional | Optional | ≤ 255 characters |
| City | Required | Optional | ≤ 100 characters |
| State | Required | Optional | US state code or DC; Canadian provinces are rejected as out of scope |
| Rack ID | Required | Optional | Positive integer |
| Retail Price | Required | Optional | USD/gal, 0.50–20.00, ≤ 8 decimals, stored exactly as Decimal |

Only `OPIS Truckstop ID` must be present as a column. Unknown columns are ignored and listed
in the preview. **Latitude/longitude columns are never imported** (see Geolocation).

## Matching and change rules

- Stations are matched **only** by `OPIS Truckstop ID` (the unique key of `FuelStation`),
  never by name or city. One batched query matches the whole file.
- **New** ID → a station is created, if Name, City, State, Rack ID and Retail Price are all
  present. Otherwise the row is rejected as *Incomplete new station*.
- **Existing** ID → values are normalized (whitespace collapsed, state upper-cased, prices
  compared numerically: `3.4500` equals `3.45`) and only fields that really differ are updated.
- **Unchanged** → skipped with no database write; `updated_at` is untouched.
- **Blank cells and omitted columns keep the stored value.** An import never clears data.
  Address placeholders without letters or digits (`-`, `.`) count as blank. To clear a
  value, edit the station in the admin form.
- **Prices:** when Retail Price is supplied, the file's prices replace the station's price
  data, as in the CLI importer: `retail_price` = lowest listed price, `max_retail_price` =
  highest, `price_observations` = number of price rows for that ID.
- `created_at` is never changed; `updated_at` changes only when a station is written.
- Stations that are not in the file are left untouched (never deleted).

## Duplicates

Rows repeating an OPIS ID follow the CLI importer's policy:

- Same address, city, state and rack ID (case-insensitive) → merged into one station
  (lowest/highest price, observation count, most frequent name). Reported as *merged*.
- Any difference in those fields → **every** row for that ID is rejected as *Conflicting
  duplicate*; nothing is guessed.

Re-uploading a file produces no new stations and no updates.

## Preview and confirmation

The preview shows total rows, new stations, updates, unchanged stations, invalid rows and
duplicate rows, followed by the changes themselves (first 50 per section): for updates,
**Current → New** per field (for example `Retail Price $3.45 → $3.29`, `City Dallas → Irving`),
the new stations, and up to 100 invalid rows with reasons. Creating a preview writes nothing
to station data.

**Confirm import** applies exactly what was previewed:

- A preview can be confirmed **once**, by its uploader, within **30 minutes**. A second
  submission (double click, back button, second tab) is refused; the button is also disabled
  after the first click.
- Inside one transaction the import is claimed, then the change plan is recomputed against
  the current database (rows locked where the database supports it). If anything differs from
  the preview — another import, an admin edit, a station created meanwhile — **nothing is
  written** and the preview is marked out of date. Upload the file again to review.
- Unpreviewed previews are deleted after a day; applied ones keep their summary and error list
  (not the rows) for the results page and error report.

### Invalid rows and rollback

Invalid rows never block valid ones. They are listed in the preview and skipped. All valid
changes (inserts, updates and the follow-up geolocation) are written in a **single database
transaction**: if anything fails, the whole import rolls back and the preview can be retried.

## Results and error report

After confirmation the results page shows rows processed, inserted, updated, unchanged,
rejected and duplicate rows, processing time and how many new or relocated stations were
placed. **Download error report (CSV)** lists every rejected row: row number, OPIS ID,
reason, reason code and detail. Values that begin with `=`, `+`, `-` or `@` are prefixed with
`'` so a spreadsheet does not run them. Internal errors and stack traces are never shown.

## Geolocation

Existing coordinates are approximate Census town points (`accuracy=city`); no station has a
verified address coordinate.

- Coordinates are **never read from the file** and never fabricated. No geocoding or routing
  request is made during an import.
- Changes to name, rack ID or price keep coordinates, accuracy, source and uncertainty
  radius unchanged.
- If address, city or state changes, the old coordinates are removed (they belong to the old
  place), then the station is re-placed at its new town from the offline Census gazetteer —
  the same step the CLI import runs. This also applies to an address-level point.
- New stations are placed the same way. If the town is not found or is ambiguous, the station
  stays **unresolved** (no coordinates) and is excluded from routing until located.
- The optimizer reads stations live and keys its per-process reuse on a station-data version
  (routable count and latest `updated_at`), so imported changes are used on the next route
  request. Cached route geometry does not depend on stations and is not recalculated.

## Measured performance

Measured on 22 Oct 2026 in a Linux container (Python 3.13, SQLite), with the real
`fuel-prices-for-be-assessment.csv` (8,151 rows → 6,626 stations, 620 Canadian rows
skipped as out of scope, 905 merged duplicates) and the same data saved as XLSX. Best of 2–3 runs:

| Step | Time |
|---|---|
| Parse CSV / XLSX | 40 ms / 1.0 s |
| Validate and merge | 0.17–0.22 s |
| Match against 6,626 stored stations | 0.23 s |
| Full preview, CSV / XLSX (incl. storing the preview) | 0.3–0.9 s / 1.5–2.0 s |
| Confirm into an empty database: 6,626 inserts + offline geolocation | 2.7–2.9 s |
| Repeat import of the same file (all unchanged) | preview 0.9 s, confirm 0.4–0.5 s |
| Price change for all 6,626 stations | preview 0.8–0.9 s, confirm 4.9–5.0 s |

The first import placed 6,228 stations at town level and left 398 unresolved, matching the
CLI-imported database. Uploading the employer CSV against that database previews 6,626
unchanged, 0 new, 0 updates. Peak traced Python memory for preview + confirm of the full
file was 45 MB. Rewriting every station is dominated by Django `bulk_update` on SQLite
(~0.75 ms per row); typical admin uploads are much smaller.

## Limitations

- The request runs synchronously (no background worker); very large files wait for the
  response. The limits above keep this to seconds.
- SQLite has no row locks; the confirmation's status claim takes SQLite's write lock before
  the re-check, which prevents an interleaved writer. On PostgreSQL rows are also locked
  with `SELECT … FOR UPDATE`.
- Values cannot be cleared through an import, and stations are never deleted by one.
- Only town-level geolocation is available; road access and exact pump locations are
  unverified, as for all existing stations.
- Excel support needs `openpyxl` (in `backend/requirements.txt`). Without it, CSV still works
  and XLSX uploads show a clear message.
