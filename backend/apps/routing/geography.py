"""Offline US geography: state names and a point-in-state test from Natural Earth polygons.

``UsBoundary`` answers "which US state (if any) contains this coordinate?" using the
Natural Earth 1:10m state polygons (public domain; see ``data/reference/SOURCE.md``).
At that scale borders and coastlines are generalised by roughly a kilometre, so points
within about a kilometre of a coast or international border can be misclassified.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from django.conf import settings

from apps.fuel.constants import US_STATE_CODES

US_STATE_NAMES: dict[str, str] = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois",
    "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana",
    "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon",
    "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota",
    "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia",
    "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
}  # fmt: skip

_STATE_BY_NAME = {name.upper(): code for code, name in US_STATE_NAMES.items()}

# US territories: real US places, but outside the 50 states + DC that the fuel data and the
# road network used here cover.
US_TERRITORY_CODES = frozenset({"PR", "GU", "VI", "AS", "MP", "UM"})


def normalise_state(value: str) -> str | None:
    """Two-letter code for a state code or full name (any case), else ``None``."""
    text = " ".join(value.strip().upper().replace(".", "").split())
    if text in US_STATE_CODES:
        return text
    return _STATE_BY_NAME.get(text)


class BoundaryDataError(Exception):
    """The boundary file is missing or malformed."""


Ring = list[tuple[float, float]]  # (longitude, latitude)


@dataclass(frozen=True)
class _Polygon:
    state: str
    exterior: Ring
    holes: tuple[Ring, ...]
    min_lon: float
    min_lat: float
    max_lon: float
    max_lat: float

    def contains(self, lon: float, lat: float) -> bool:
        if not (self.min_lon <= lon <= self.max_lon and self.min_lat <= lat <= self.max_lat):
            return False
        return _ring_contains(self.exterior, lon, lat) and not any(
            _ring_contains(hole, lon, lat) for hole in self.holes
        )


def _ring_contains(ring: Ring, x: float, y: float) -> bool:
    """Even-odd ray casting."""
    inside = False
    x1, y1 = ring[-1]
    for x2, y2 in ring:
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
        x1, y1 = x2, y2
    return inside


class UsBoundary:
    def __init__(self, polygons: list[_Polygon]) -> None:
        self._polygons = polygons

    @classmethod
    def from_file(cls, path: Path) -> UsBoundary:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            polygons = []
            for feature in data["features"]:
                state = feature["properties"]["state"]
                for rings in feature["geometry"]["coordinates"]:
                    exterior = [(float(x), float(y)) for x, y in rings[0]]
                    lons = [x for x, _ in exterior]
                    lats = [y for _, y in exterior]
                    polygons.append(
                        _Polygon(
                            state=state,
                            exterior=exterior,
                            holes=tuple([(float(x), float(y)) for x, y in r] for r in rings[1:]),
                            min_lon=min(lons),
                            min_lat=min(lats),
                            max_lon=max(lons),
                            max_lat=max(lats),
                        )
                    )
        except FileNotFoundError as exc:
            raise BoundaryDataError(f"US boundary file not found: {path}") from exc
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise BoundaryDataError(f"US boundary file is malformed: {exc}") from exc
        if not polygons:
            raise BoundaryDataError("US boundary file contains no polygons.")
        return cls(polygons)

    def state_at(self, latitude: float, longitude: float) -> str | None:
        for polygon in self._polygons:
            if polygon.contains(longitude, latitude):
                return polygon.state
        return None


@lru_cache(maxsize=1)
def get_us_boundary() -> UsBoundary:
    return UsBoundary.from_file(settings.US_STATE_BOUNDARIES_PATH)
