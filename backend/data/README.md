# Data

| File | What it is |
|------|------------|
| `fuel-prices-for-be-assessment.csv` | Employer-provided fuel prices (8,151 rows). Imported by `python manage.py import_fuel_prices`. |
| `reference/Gaz_places_national.txt` | US Census place gazetteer: station geolocation (M1) and `"City, ST"` resolution for routes (M2). See `reference/SOURCE.md`. |
| `reference/us_states_ne_10m.geojson` | US state + DC polygons (Natural Earth 1:10m) used to check that coordinate inputs are inside the US (M2). See `reference/SOURCE.md`. |

The CSV is read only by management commands. The two reference files are loaded once per
server process into memory (at startup via `config/wsgi.py`/`asgi.py`); no request re-reads them.
