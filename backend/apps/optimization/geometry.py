"""Place points along a route polyline. Pure Python: no database, no network.

* Segment lengths use the haversine formula on a spherical Earth (mean radius).
* A point's nearest position on the route is found with a local equirectangular projection
  centred on the point (error well under 1% within the few tens of miles searched).
* A uniform grid over segment bounding boxes keeps the search to nearby segments, so the
  cost per point does not grow with route length.
* Matching runs on a thinned copy of the line (vertices >= 0.5 mile apart, which turns a
  ~40k-point coast-to-coast OSRM geometry into ~5k vertices) whose vertices keep their
  distance along the full line.

Mile markers are geometric distances along the polyline, then scaled so the polyline's total
length equals the provider's driving distance (the two differ slightly because the polyline
is a chain of straight segments).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

EARTH_RADIUS_MILES = 3958.7613  # IUGG mean radius
MILES_PER_DEGREE = EARTH_RADIUS_MILES * math.pi / 180  # ~69.09 along a meridian
GRID_DEGREES = 0.25
MIN_VERTEX_SPACING_MILES = 0.5


def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = phi2 - phi1
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlmb / 2) ** 2
    return 2 * EARTH_RADIUS_MILES * math.asin(min(1.0, math.sqrt(a)))


@dataclass(frozen=True)
class RoutePosition:
    mile: float  # along the route, scaled to the provider distance
    offset_miles: float  # straight-line distance from the point to the route


class RouteLine:
    """A GeoJSON LineString (``[lon, lat]`` positions) with cumulative distances."""

    def __init__(self, coordinates: Sequence[Sequence[float]], distance_miles: float) -> None:
        if len(coordinates) < 2:
            raise ValueError("A route needs at least two points.")
        # One pass: haversine length of every segment (trigonometry computed once per point),
        # and a thinned copy for matching: vertices at least MIN_VERTEX_SPACING_MILES apart,
        # each keeping its distance along the *full* line, so mile markers stay exact at
        # vertices. On highway curves the thinned chord stays well within 0.1 mile of the road.
        radians, sin, cos, asin, sqrt = math.radians, math.sin, math.cos, math.asin, math.sqrt
        two_r = 2 * EARTH_RADIUS_MILES
        lon0, lat0 = coordinates[0]
        prev_phi, prev_lambda = radians(lat0), radians(lon0)
        prev_cos = cos(prev_phi)
        points = [(float(lat0), float(lon0))]
        cumulative = [0.0]
        total = 0.0
        last = len(coordinates) - 1
        for index in range(1, last + 1):
            lon, lat = coordinates[index]
            phi, lmb = radians(lat), radians(lon)
            cos_phi = cos(phi)
            a = (
                sin((phi - prev_phi) / 2) ** 2
                + cos_phi * prev_cos * sin((lmb - prev_lambda) / 2) ** 2
            )
            total += two_r * asin(min(1.0, sqrt(a)))
            if index == last or total - cumulative[-1] >= MIN_VERTEX_SPACING_MILES:
                points.append((float(lat), float(lon)))
                cumulative.append(total)
            prev_phi, prev_lambda, prev_cos = phi, lmb, cos_phi

        self.points = points
        self.cumulative = cumulative
        self.geometric_miles = total
        self.distance_miles = distance_miles
        self.scale = distance_miles / total if total > 0 else 0.0
        self._grid: dict[tuple[int, int], list[int]] = {}
        for index in range(len(points) - 1):
            (lat1, lon1), (lat2, lon2) = points[index], points[index + 1]
            for cell in _cells(min(lat1, lat2), max(lat1, lat2), min(lon1, lon2), max(lon1, lon2)):
                self._grid.setdefault(cell, []).append(index)

    def locate(
        self, latitude: float, longitude: float, max_offset_miles: float
    ) -> RoutePosition | None:
        """Nearest route position within ``max_offset_miles`` of the point, else ``None``.

        If the route passes the point more than once, the closest pass wins (earliest on ties).
        """
        dlat = max_offset_miles / MILES_PER_DEGREE
        coslat = max(math.cos(math.radians(latitude)), 1e-6)
        dlon = dlat / coslat
        segments = sorted(
            {
                index
                for cell in _cells(
                    latitude - dlat, latitude + dlat, longitude - dlon, longitude + dlon
                )
                for index in self._grid.get(cell, ())
            }
        )
        best: tuple[float, int, float] | None = None  # (offset, segment index, t)
        kx = MILES_PER_DEGREE * coslat
        for index in segments:
            (lat1, lon1), (lat2, lon2) = self.points[index], self.points[index + 1]
            ax, ay = (lon1 - longitude) * kx, (lat1 - latitude) * MILES_PER_DEGREE
            bx, by = (lon2 - longitude) * kx, (lat2 - latitude) * MILES_PER_DEGREE
            dx, dy = bx - ax, by - ay
            length_sq = dx * dx + dy * dy
            t = 0.0 if length_sq == 0 else min(1.0, max(0.0, -(ax * dx + ay * dy) / length_sq))
            offset = math.hypot(ax + t * dx, ay + t * dy)
            if offset <= max_offset_miles and (best is None or offset < best[0]):
                best = (offset, index, t)
        if best is None:
            return None
        offset, index, t = best
        segment = self.cumulative[index + 1] - self.cumulative[index]
        geometric_mile = self.cumulative[index] + t * segment
        return RoutePosition(mile=geometric_mile * self.scale, offset_miles=offset)


def _cells(min_lat: float, max_lat: float, min_lon: float, max_lon: float) -> list[tuple[int, int]]:
    rows = range(math.floor(min_lat / GRID_DEGREES), math.floor(max_lat / GRID_DEGREES) + 1)
    cols = range(math.floor(min_lon / GRID_DEGREES), math.floor(max_lon / GRID_DEGREES) + 1)
    return [(row, col) for row in rows for col in cols]


METERS_PER_MILE = 1609.344


def simplify(coordinates: Sequence[Sequence[float]], tolerance_meters: float) -> list[list[float]]:
    """Douglas-Peucker simplification of ``[lon, lat]`` positions, for display only.

    Every dropped point lies within ``tolerance_meters`` of the simplified line (measured in a
    local equirectangular projection at the segment's mid-latitude). Endpoints are always
    kept. Iterative, so long routes cannot hit the recursion limit.
    """
    count = len(coordinates)
    if count <= 2:
        return [list(p) for p in coordinates]
    tolerance_sq = (tolerance_meters / METERS_PER_MILE) ** 2
    keep = [False] * count
    keep[0] = keep[-1] = True
    stack = [(0, count - 1)]
    while stack:
        first, last = stack.pop()
        if last - first < 2:
            continue
        lon1, lat1 = coordinates[first]
        lon2, lat2 = coordinates[last]
        kx = MILES_PER_DEGREE * math.cos(math.radians((lat1 + lat2) / 2))
        ky = MILES_PER_DEGREE
        dx, dy = (lon2 - lon1) * kx, (lat2 - lat1) * ky
        length_sq = dx * dx + dy * dy
        worst, worst_index = -1.0, -1
        for index in range(first + 1, last):
            lon, lat = coordinates[index]
            px, py = (lon - lon1) * kx, (lat - lat1) * ky
            projection = px * dx + py * dy
            if length_sq == 0 or projection <= 0:
                distance_sq = px * px + py * py
            elif projection >= length_sq:
                ex, ey = px - dx, py - dy
                distance_sq = ex * ex + ey * ey
            else:
                cross = px * dy - py * dx
                distance_sq = cross * cross / length_sq
            if distance_sq > worst:
                worst, worst_index = distance_sq, index
        if worst > tolerance_sq:
            keep[worst_index] = True
            stack.append((first, worst_index))
            stack.append((worst_index, last))
    return [list(coordinates[i]) for i in range(count) if keep[i]]
