"""Offline, city-level station geolocation from the US Census Gazetteer.

The supplied CSV has no coordinates, and almost every address is a highway-exit
description ("I-44, EXIT 283 & US-69"), which street geocoders cannot place reliably.
Instead, each station's *city/state* is matched to a Census place and gets that place's
internal point, marked ``accuracy=city`` with an uncertainty radius. These are
approximations of the town, never of the truck stop itself. Stations whose city cannot
be matched unambiguously stay ``unresolved`` with no coordinates.

No network calls are made; the gazetteer is a local, public-domain file.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections.abc import Collection, Iterable
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path

from django.db import connection, transaction
from django.utils import timezone

from apps.fuel.models import FuelStation, GeolocationAccuracy, GeolocationSource

GAZETTEER_SOURCE = GeolocationSource.CENSUS_GAZETTEER_PLACES_2010
GAZETTEER_ENCODING = "latin-1"  # The 2010 Census file is ISO-8859-1 ("Cañon City").
_REQUIRED_GAZETTEER_COLUMNS = ("USPS", "NAME", "ALAND_SQMI", "INTPTLAT", "INTPTLONG")

# Lower-case legal/statistical descriptors the Census appends to place names.
# Case matters: "Carson City" is a name, "Tomah city" is "Tomah" + descriptor.
_DESCRIPTORS = sorted(
    [
        " (balance)",
        " city and borough",
        " metropolitan government",
        " metro government",
        " consolidated government",
        " unified government",
        " urban county",
        " municipality",
        " corporation",
        " zona urbana",
        " comunidad",
        " borough",
        " village",
        " city",
        " town",
        " CDP",
    ],
    key=len,
    reverse=True,
)
_CONSOLIDATED_MARKERS = ("(balance)", "government")
MIN_UNCERTAINTY_MILES = 1.0
BULK_BATCH_SIZE = 500


class GazetteerError(Exception):
    """The gazetteer file is missing or not in the expected format."""


def strip_descriptors(name: str) -> str:
    stripped = name.strip()
    changed = True
    while changed:
        changed = False
        for suffix in _DESCRIPTORS:
            if stripped.endswith(suffix):
                stripped = stripped[: -len(suffix)].rstrip()
                changed = True
    return stripped


def place_key(name: str) -> str:
    """Comparable form of a place name: ASCII, upper case, unified abbreviations."""
    text = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    text = text.upper().replace(".", "").replace("'", "")
    text = " ".join(re.sub(r"[-/]", " ", text).split())
    text = re.sub(r"^(ST|STE) ", "SAINT ", text)
    text = re.sub(r"^FT ", "FORT ", text)
    text = re.sub(r"^MT ", "MOUNT ", text)
    return text


@dataclass(frozen=True)
class Place:
    name: str
    state: str
    latitude: float
    longitude: float
    land_area_sq_miles: float

    @property
    def uncertainty_miles(self) -> float:
        """Radius of a circle with the place's land area: a rough spread for the town."""
        radius = math.sqrt(max(self.land_area_sq_miles, 0.0) / math.pi)
        return round(max(radius, MIN_UNCERTAINTY_MILES), 1)


class MatchStatus(StrEnum):
    MATCHED = "matched"
    AMBIGUOUS = "ambiguous"
    NOT_FOUND = "not_found"


@dataclass(frozen=True)
class Match:
    status: MatchStatus
    place: Place | None = None
    candidates: tuple[Place, ...] = ()  # the competing places when ambiguous


class Gazetteer:
    """In-memory index of Census places by (state, normalised name)."""

    def __init__(self, places: list[Place]) -> None:
        self._exact: dict[tuple[str, str], list[Place]] = {}
        self._compact: dict[tuple[str, str], list[Place]] = {}
        self._alias: dict[tuple[str, str], list[Place]] = {}
        for place in places:
            key = place_key(strip_descriptors(place.name))
            self._exact.setdefault((place.state, key), []).append(place)
            self._compact.setdefault((place.state, key.replace(" ", "")), []).append(place)
            # "Indianapolis city (balance)", "Augusta-Richmond County consolidated government"
            # are also known by their first segment ("Augusta").
            if any(marker in place.name for marker in _CONSOLIDATED_MARKERS):
                first = re.split(r"[-/]", strip_descriptors(place.name), maxsplit=1)[0]
                self._alias.setdefault((place.state, place_key(first)), []).append(place)

    def __len__(self) -> int:
        return sum(len(v) for v in self._exact.values())

    @classmethod
    def from_file(cls, path: Path) -> Gazetteer:
        try:
            with path.open(encoding=GAZETTEER_ENCODING) as handle:
                header = [col.strip() for col in handle.readline().split("\t")]
                missing = [col for col in _REQUIRED_GAZETTEER_COLUMNS if col not in header]
                if missing:
                    raise GazetteerError(f"Gazetteer is missing columns: {', '.join(missing)}")
                idx = {col: header.index(col) for col in _REQUIRED_GAZETTEER_COLUMNS}
                places = []
                for number, line in enumerate(handle, start=2):
                    cells = [cell.strip() for cell in line.rstrip("\n").split("\t")]
                    if len(cells) < len(header):
                        raise GazetteerError(f"Gazetteer line {number} has too few columns")
                    try:
                        places.append(
                            Place(
                                name=cells[idx["NAME"]],
                                state=cells[idx["USPS"]],
                                latitude=float(cells[idx["INTPTLAT"]]),
                                longitude=float(cells[idx["INTPTLONG"]]),
                                land_area_sq_miles=float(cells[idx["ALAND_SQMI"]]),
                            )
                        )
                    except ValueError as exc:
                        raise GazetteerError(f"Gazetteer line {number}: {exc}") from exc
        except FileNotFoundError as exc:
            raise GazetteerError(f"Gazetteer file not found: {path}") from exc
        return cls(places)

    def lookup(self, city: str, state: str) -> Match:
        key = place_key(city)
        attempts = (
            (self._exact, key),
            (self._compact, key.replace(" ", "")),  # "Mc Calla" -> "McCalla"
            (self._exact, f"{key} CITY"),  # "Boise" -> "Boise City"
            (self._alias, key),  # "Indianapolis" -> "Indianapolis city (balance)"
        )
        for index, candidate in attempts:
            places = index.get((state, candidate), [])
            if len(places) == 1:
                return Match(MatchStatus.MATCHED, places[0])
            if len(places) > 1:
                return Match(MatchStatus.AMBIGUOUS, candidates=tuple(places))
        return Match(MatchStatus.NOT_FOUND)


def validate_coordinates(latitude: float, longitude: float) -> None:
    """Raise ``ValueError`` unless the pair is a finite, in-range WGS84 coordinate."""
    if not (math.isfinite(latitude) and math.isfinite(longitude)):
        raise ValueError("Coordinates must be finite numbers.")
    if not -90.0 <= latitude <= 90.0:
        raise ValueError(f"Latitude {latitude} is outside -90..90.")
    if not -180.0 <= longitude <= 180.0:
        raise ValueError(f"Longitude {longitude} is outside -180..180.")


@dataclass
class GeolocationResult:
    considered: int = 0
    resolved: int = 0
    ambiguous: int = 0
    not_found: int = 0
    distinct_places_looked_up: int = 0
    unresolved_examples: list[str] = field(default_factory=list)


def geolocate_stations(
    gazetteer: Gazetteer, *, force: bool = False, opis_ids: Collection[int] | None = None
) -> GeolocationResult:
    """Assign city-level coordinates to unresolved stations (all city-level ones with ``force``).

    Address-level coordinates, if ever added, are never overwritten. Lookups are cached per
    (city, state) for the run; results persist on the rows, so reruns skip resolved stations.
    ``opis_ids`` limits the run to those stations (the admin import passes the ones it touched).
    """
    eligible = [GeolocationAccuracy.UNRESOLVED]
    if force:
        eligible.append(GeolocationAccuracy.CITY)
    queryset = FuelStation.objects.filter(geolocation_accuracy__in=eligible)
    fields = ("id", "city", "state", "geolocation_accuracy")
    if opis_ids is None:
        stations: Iterable[tuple[int, str, str, str]] = queryset.values_list(*fields)
    else:
        ids = sorted(opis_ids)
        stations = [
            row
            for start in range(0, len(ids), BULK_BATCH_SIZE)
            for row in queryset.filter(opis_id__in=ids[start : start + BULK_BATCH_SIZE])
            .order_by("id")
            .values_list(*fields)
        ]

    result = GeolocationResult()
    cache: dict[tuple[str, str], Match] = {}
    # Stations in the same city receive identical values, so writes are grouped by outcome:
    # one UPDATE ... WHERE id IN (...) per place is far cheaper in SQLite than bulk_update's
    # per-row CASE expressions (measured: 7.1s -> see docs/architecture.md).
    updates: dict[Place | None, list[int]] = {}
    for station_id, city, state, accuracy in stations:
        result.considered += 1
        if (city, state) not in cache:
            cache[(city, state)] = gazetteer.lookup(city, state)
        match = cache[(city, state)]

        if match.place is not None:
            validate_coordinates(match.place.latitude, match.place.longitude)
            result.resolved += 1
            updates.setdefault(match.place, []).append(station_id)
            continue
        if match.status is MatchStatus.AMBIGUOUS:
            result.ambiguous += 1
        else:
            result.not_found += 1
        if len(result.unresolved_examples) < 10:
            result.unresolved_examples.append(f"{city}, {state} ({match.status})")
        if accuracy != GeolocationAccuracy.UNRESOLVED:  # only reachable with force=True
            updates.setdefault(None, []).append(station_id)

    result.distinct_places_looked_up = len(cache)
    _write_geolocation(updates, timezone.now())
    return result


def _write_geolocation(updates: dict[Place | None, list[int]], now: datetime) -> None:
    """Persist all outcomes in one transaction. Every backend gets identical values.

    Only the statement shape differs. On local SQLite one ``UPDATE ... WHERE id IN (...)`` per
    place is fastest. On a networked database (Neon) each of those ~3,500 statements is a
    round trip, which took minutes and left a long transaction exposed to interruption, so
    ``bulk_update`` writes the same values with one statement per batch of stations.
    """
    with transaction.atomic():
        if connection.vendor == "sqlite":
            for place, ids in updates.items():
                for start in range(0, len(ids), BULK_BATCH_SIZE):
                    batch = FuelStation.objects.filter(pk__in=ids[start : start + BULK_BATCH_SIZE])
                    batch.update(**_geolocation_values(place), updated_at=now)
            return
        stations = [
            FuelStation(pk=station_id, updated_at=now, **_geolocation_values(place))
            for place, ids in updates.items()
            for station_id in ids
        ]
        FuelStation.objects.bulk_update(
            stations, [*_geolocation_values(None), "updated_at"], batch_size=BULK_BATCH_SIZE
        )


def _geolocation_values(place: Place | None) -> dict[str, object]:
    if place is None:
        return {
            "latitude": None,
            "longitude": None,
            "geolocation_source": GeolocationSource.NONE,
            "geolocation_accuracy": GeolocationAccuracy.UNRESOLVED,
            "location_uncertainty_miles": None,
        }
    return {
        "latitude": place.latitude,
        "longitude": place.longitude,
        "geolocation_source": GAZETTEER_SOURCE,
        "geolocation_accuracy": GeolocationAccuracy.CITY,
        "location_uncertainty_miles": place.uncertainty_miles,
    }
