"""Stand-in routes for repeatable offline benchmarks. NOT real road geometry.

Each route is a polyline through the Census points of towns along the named interstate,
densified to a fixed spacing so its size resembles OSRM's full-overview geometry (one point
every ~60-300 m). Distances are the public OSRM server's driving distance for the pair where
known (fetched 2026-10-21), otherwise the polyline length x 1.02.

The stand-ins exercise the real station database, geometry, optimiser, cache and serialiser
with realistic payload sizes. They say nothing about real routing latency or which stations a
real road route would pass.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import httpx

from apps.optimization.geometry import haversine_miles
from apps.routing.locations import get_gazetteer
from apps.routing.providers import METERS_PER_MILE, OsrmProvider


@dataclass(frozen=True)
class StandInRoute:
    name: str
    start: str
    finish: str
    towns: tuple[str, ...]
    osrm_meters: float | None  # public OSRM distance for start->finish, if known


STAND_IN_ROUTES = {
    route.name: route
    for route in (
        StandInRoute(
            "dallas-atlanta",
            "Dallas, TX",
            "Atlanta, GA",
            ("Dallas, TX", "Tyler, TX", "Shreveport, LA", "Monroe, LA", "Vicksburg, MS",
             "Jackson, MS", "Meridian, MS", "Birmingham, AL", "Anniston, AL", "Atlanta, GA"),
            1253364.0,
        ),
        StandInRoute(
            "newyork-losangeles",
            "New York, NY",
            "Los Angeles, CA",
            ("New York, NY", "Newark, NJ", "Harrisburg, PA", "Pittsburgh, PA", "Columbus, OH",
             "Indianapolis, IN", "Effingham, IL", "St. Louis, MO", "Joplin, MO", "Tulsa, OK",
             "Oklahoma City, OK", "Amarillo, TX", "Albuquerque, NM", "Flagstaff, AZ",
             "Kingman, AZ", "Barstow, CA", "Los Angeles, CA"),
            4496847.5,
        ),
        StandInRoute(
            "seattle-miami",
            "Seattle, WA",
            "Miami, FL",
            ("Seattle, WA", "Spokane, WA", "Missoula, MT", "Billings, MT", "Sheridan, WY",
             "Casper, WY", "Cheyenne, WY", "Denver, CO", "Wichita, KS", "Tulsa, OK",
             "Little Rock, AR", "Memphis, TN", "Birmingham, AL", "Atlanta, GA", "Macon, GA",
             "Valdosta, GA", "Gainesville, FL", "Orlando, FL", "Miami, FL"),
            None,
        ),
    )
}  # fmt: skip


def stand_in_geometry(route: StandInRoute, spacing_miles: float) -> tuple[list[list[float]], float]:
    """``([lon, lat], ...)`` positions and a distance in metres."""
    gazetteer = get_gazetteer()
    points = []
    for town in route.towns:
        city, state = (part.strip() for part in town.rsplit(",", 1))
        place = gazetteer.lookup(city, state).place
        if place is None:
            raise ValueError(f"Stand-in town not in gazetteer: {town}")
        points.append((place.latitude, place.longitude))
    coords: list[list[float]] = []
    for (lat1, lon1), (lat2, lon2) in zip(points, points[1:], strict=False):
        steps = max(1, int(haversine_miles(lat1, lon1, lat2, lon2) / spacing_miles))
        for i in range(steps):
            coords.append(
                [
                    round(lon1 + (lon2 - lon1) * i / steps, 6),
                    round(lat1 + (lat2 - lat1) * i / steps, 6),
                ]
            )
    coords.append([points[-1][1], points[-1][0]])
    if route.osrm_meters is not None:
        return coords, route.osrm_meters
    length = sum(
        haversine_miles(a[1], a[0], b[1], b[0]) for a, b in zip(coords, coords[1:], strict=False)
    )
    return coords, length * 1.02 * METERS_PER_MILE


class StandInOsrm:
    """An ``OsrmProvider`` whose HTTP transport is answered in-process with a stand-in route.

    Everything after the socket is the production code path: request building, JSON parsing,
    validation and normalisation.
    """

    def __init__(self, coords: list[list[float]], meters: float) -> None:
        self.requests = 0
        self._body = json.dumps(
            {
                "code": "Ok",
                "routes": [
                    {
                        "distance": meters,
                        "duration": 0.0,
                        "geometry": {"type": "LineString", "coordinates": coords},
                    }
                ],
                "waypoints": [],
            }
        ).encode()

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests += 1
        return httpx.Response(200, content=self._body, headers={"Content-Type": "application/json"})

    def provider(self) -> OsrmProvider:
        return OsrmProvider(
            "https://stand-in.invalid",
            timeout=10,
            user_agent="RouteFuel-benchmark",
            transport=httpx.MockTransport(self._handle),
        )
