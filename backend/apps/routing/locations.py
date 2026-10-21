"""Resolve user-supplied start/finish values into US coordinates, entirely offline.

* ``"City, ST"`` (or ``"City, State Name"``) is matched against the Census places gazetteer
  already used for fuel stations in M1. The result is the place's Census internal point.
  If two places in the state share the name, the request is rejected rather than guessed.
* ``{"latitude", "longitude"}`` must fall inside a US state (or DC) polygon.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from django.conf import settings

from apps.fuel.constants import CANADIAN_PROVINCE_CODES
from apps.fuel.geolocation import Gazetteer, MatchStatus, strip_descriptors
from apps.routing.geography import US_TERRITORY_CODES, get_us_boundary, normalise_state

MAX_AMBIGUOUS_CANDIDATES = 10


@dataclass(frozen=True)
class PlaceQuery:
    city: str
    state: str  # as typed; normalised during resolution


@dataclass(frozen=True)
class CoordinateQuery:
    latitude: float
    longitude: float


LocationQuery = PlaceQuery | CoordinateQuery


@dataclass(frozen=True)
class ResolvedLocation:
    label: str
    latitude: float
    longitude: float
    state: str
    source: str  # "census_place" or "coordinates"


class LocationError(Exception):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}
        self.field: str | None = None  # set by the caller: "start" or "finish"


@lru_cache(maxsize=1)
def get_gazetteer() -> Gazetteer:
    return Gazetteer.from_file(settings.GAZETTEER_PLACES_PATH)


def resolve_location(query: LocationQuery) -> ResolvedLocation:
    if isinstance(query, CoordinateQuery):
        return _resolve_coordinates(query)
    return _resolve_place(query)


def _resolve_coordinates(query: CoordinateQuery) -> ResolvedLocation:
    state = get_us_boundary().state_at(query.latitude, query.longitude)
    if state is None:
        raise LocationError(
            "location_outside_us",
            "The coordinates are not inside one of the 50 US states or DC.",
            {"latitude": query.latitude, "longitude": query.longitude},
        )
    return ResolvedLocation(
        label=f"{query.latitude:.5f}, {query.longitude:.5f}",
        latitude=query.latitude,
        longitude=query.longitude,
        state=state,
        source="coordinates",
    )


def _resolve_place(query: PlaceQuery) -> ResolvedLocation:
    state = normalise_state(query.state)
    if state is None:
        typed = query.state.strip().upper()
        if typed in CANADIAN_PROVINCE_CODES or typed in US_TERRITORY_CODES:
            raise LocationError(
                "location_outside_us",
                f"'{query.state.strip()}' is outside the supported area (the 50 US states and DC).",
                {"state": query.state.strip()},
            )
        raise LocationError(
            "location_not_found",
            f"'{query.state.strip()}' is not a US state code or name.",
            {"state": query.state.strip()},
        )

    match = get_gazetteer().lookup(query.city, state)
    if match.status is MatchStatus.AMBIGUOUS:
        candidates = [
            {"name": place.name, "latitude": place.latitude, "longitude": place.longitude}
            for place in match.candidates[:MAX_AMBIGUOUS_CANDIDATES]
        ]
        raise LocationError(
            "ambiguous_location",
            f"'{query.city}, {state}' matches {len(match.candidates)} Census places. "
            "Send coordinates instead.",
            {"city": query.city, "state": state, "candidates": candidates},
        )
    if match.place is None:
        raise LocationError(
            "location_not_found",
            f"No US Census place named '{query.city}' in {state}.",
            {"city": query.city, "state": state},
        )

    place = match.place
    return ResolvedLocation(
        label=f"{strip_descriptors(place.name)}, {state}",
        latitude=place.latitude,
        longitude=place.longitude,
        state=state,
        source="census_place",
    )


def preload_reference_data() -> None:
    """Load the gazetteer and state polygons now rather than on the first request."""
    get_gazetteer()
    get_us_boundary()
