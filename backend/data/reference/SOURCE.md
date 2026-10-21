# Gaz_places_national.txt

| | |
|---|---|
| Publisher | U.S. Census Bureau, 2010 Census Gazetteer Files — Places |
| Original URL | https://www2.census.gov/geo/docs/maps-data/data/gazetteer/Gaz_places_national.zip |
| Obtained from | Unmodified copy in https://github.com/publicdocs-platform/us-cities-db (Census.gov was not reachable from the build environment) |
| SHA-256 | `40695d5852a48282241d9e63f1ef8ce388ae3b89f0b0f7fbe68d63452225dd24` |
| Encoding | ISO-8859-1 (Latin-1), tab-separated |
| Rows | 29,514 incorporated places and Census Designated Places (50 states, DC, PR) |
| License | Public domain (work of the U.S. Government, 17 U.S.C. § 105) |

Columns used: `USPS` (state), `NAME`, `ALAND_SQMI` (land area), `INTPTLAT`/`INTPTLONG`
(the Census "internal point", a point guaranteed inside the place — not a station location).

To refresh with a newer vintage, download the current "Places" gazetteer from
https://www.census.gov/geographies/reference-files/time-series/geo/gazetteer-files.html,
replace this file, and run `python manage.py geolocate_stations --force`. The columns used
above are the same in later vintages (newer files drop the `POP10`/`HU10` columns, which are
not read).
