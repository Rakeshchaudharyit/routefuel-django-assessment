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

# us_states_ne_10m.geojson

| | |
|---|---|
| Publisher | Natural Earth, *Admin 1 – States, Provinces*, 1:10m scale |
| Obtained from | `geojson/ne_10m_admin_1_states_provinces.geojson` in https://github.com/nvkelso/natural-earth-vector (version `5.2.0-pre`, commit `ca96624a56bd078437bca8184e78163e5039ad19`) |
| Source SHA-256 | `22d0e3ad85eb3e27f17cabf8ba2d50e554fbc27a87796ff891d958185da62fb5` |
| Derived file SHA-256 | `6908c0aeaa34d249714de64235081da486f60a8012c5d09cc06595bdc3239002` |
| Contents | 51 features (50 states + DC), each a MultiPolygon; properties `state` (USPS code) and `name` |
| License | Public domain (Natural Earth terms of use) |

Derivation: keep features with `adm0_a3 == "USA"`, convert every geometry to MultiPolygon,
round coordinates to 5 decimal places, keep only `postal` (as `state`) and `name`:

```python
import json
src = json.load(open("ne_10m_admin_1_states_provinces.geojson"))
features = []
for f in sorted((f for f in src["features"] if f["properties"].get("adm0_a3") == "USA"),
                key=lambda f: f["properties"]["postal"]):
    g = f["geometry"]
    polys = [g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"]
    features.append({"type": "Feature",
                     "properties": {"state": f["properties"]["postal"], "name": f["properties"]["name"]},
                     "geometry": {"type": "MultiPolygon", "coordinates":
                                  [[[[round(x, 5), round(y, 5)] for x, y in ring] for ring in poly]
                                   for poly in polys]}})
json.dump({"type": "FeatureCollection", "features": features},
          open("us_states_ne_10m.geojson", "w"), separators=(",", ":"))
```

Accuracy: 1:10m generalisation moves borders and coastlines by up to roughly a kilometre, so a
coordinate very close to a coast or the Canada/Mexico border can be classified wrongly. Large
lakes and bays inside state boundaries (e.g. Lake Michigan) count as inside the state.
