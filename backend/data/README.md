# Data

| File | What it is |
|------|------------|
| `fuel-prices-for-be-assessment.csv` | Employer-provided fuel prices (8,151 rows). Imported by `python manage.py import_fuel_prices`. |
| `reference/Gaz_places_national.txt` | US Census place gazetteer used for offline, city-level geolocation. See `reference/SOURCE.md`. |

Both files are read only by management commands. API requests read from SQLite, never from these files.
