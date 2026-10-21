"""Reusable station queries for route matching (consumed from M3).

Route matching will be two-stage: a cheap indexed bounding-box query here, then exact
distance-to-route checks in Python on the much smaller candidate set.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass

from django.db.models import QuerySet

from apps.fuel.geolocation import validate_coordinates
from apps.fuel.models import FuelStation, GeolocationAccuracy

MILES_PER_DEGREE_LATITUDE = 69.0


@dataclass(frozen=True)
class BoundingBox:
    min_latitude: float
    max_latitude: float
    min_longitude: float
    max_longitude: float

    def __post_init__(self) -> None:
        validate_coordinates(self.min_latitude, self.min_longitude)
        validate_coordinates(self.max_latitude, self.max_longitude)
        if self.min_latitude > self.max_latitude or self.min_longitude > self.max_longitude:
            raise ValueError("Bounding box minimums must not exceed maximums.")

    @classmethod
    def around(
        cls, points: Iterable[tuple[float, float]], padding_miles: float = 0.0
    ) -> BoundingBox:
        """Smallest box containing ``(latitude, longitude)`` points, padded on every side.

        Does not handle boxes crossing the antimeridian (irrelevant for US road trips).
        """
        if padding_miles < 0:
            raise ValueError("padding_miles must not be negative.")
        pts = list(points)
        if not pts:
            raise ValueError("At least one point is required.")
        for lat, lng in pts:
            validate_coordinates(lat, lng)
        lats = [lat for lat, _ in pts]
        lngs = [lng for _, lng in pts]

        lat_pad = padding_miles / MILES_PER_DEGREE_LATITUDE
        # A degree of longitude shrinks with latitude; pad using the widest-latitude edge.
        widest = min(max(abs(min(lats)), abs(max(lats))) + lat_pad, 89.0)
        lng_pad = padding_miles / (MILES_PER_DEGREE_LATITUDE * math.cos(math.radians(widest)))
        return cls(
            min_latitude=max(min(lats) - lat_pad, -90.0),
            max_latitude=min(max(lats) + lat_pad, 90.0),
            min_longitude=max(min(lngs) - lng_pad, -180.0),
            max_longitude=min(max(lngs) + lng_pad, 180.0),
        )


def routable_stations() -> QuerySet[FuelStation]:
    """Stations with coordinates. Unresolved stations are never route candidates."""
    return FuelStation.objects.exclude(geolocation_accuracy=GeolocationAccuracy.UNRESOLVED).filter(
        latitude__isnull=False, longitude__isnull=False
    )


def stations_in_bounding_box(box: BoundingBox) -> QuerySet[FuelStation]:
    """Routable stations inside ``box`` (uses the latitude/longitude index)."""
    return routable_stations().filter(
        latitude__gte=box.min_latitude,
        latitude__lte=box.max_latitude,
        longitude__gte=box.min_longitude,
        longitude__lte=box.max_longitude,
    )
