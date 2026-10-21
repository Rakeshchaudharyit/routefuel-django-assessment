"""Route mile markers and station-to-route distances."""

from __future__ import annotations

import math
import random

import pytest

from apps.optimization.geometry import (
    MILES_PER_DEGREE,
    RouteLine,
    haversine_miles,
)


def test_haversine_known_distances() -> None:
    # One degree of latitude on the mean-radius sphere.
    assert haversine_miles(0, 0, 1, 0) == pytest.approx(MILES_PER_DEGREE, rel=1e-12)
    # Cross-check with the spherical law of cosines (independent formula, same sphere).
    lat1, lon1, lat2, lon2 = map(math.radians, (32.794176, -96.765503, 33.762909, -84.422675))
    central = math.acos(
        math.sin(lat1) * math.sin(lat2) + math.cos(lat1) * math.cos(lat2) * math.cos(lon2 - lon1)
    )
    assert haversine_miles(32.794176, -96.765503, 33.762909, -84.422675) == pytest.approx(
        central * 3958.7613, rel=1e-9
    )
    assert haversine_miles(40.0, -100.0, 40.0, -100.0) == 0


def test_cumulative_distance_and_scale() -> None:
    line = RouteLine([[-100.0, 35.0], [-100.0, 36.0], [-100.0, 37.0]], distance_miles=150.0)

    assert line.cumulative[1] == pytest.approx(MILES_PER_DEGREE)
    assert line.geometric_miles == pytest.approx(2 * MILES_PER_DEGREE)
    assert line.scale == pytest.approx(150.0 / (2 * MILES_PER_DEGREE))


def test_mile_markers_are_scaled_to_provider_distance() -> None:
    line = RouteLine([[-100.0, 35.0], [-100.0, 37.0]], distance_miles=200.0)

    midpoint = line.locate(36.0, -100.0, max_offset_miles=1)
    end = line.locate(37.0, -100.0, max_offset_miles=1)

    assert midpoint is not None and end is not None
    assert midpoint.mile == pytest.approx(100.0, abs=0.05)
    assert end.mile == pytest.approx(200.0)
    assert midpoint.offset_miles == pytest.approx(0, abs=1e-9)


def test_offset_is_perpendicular_distance_in_miles() -> None:
    line = RouteLine([[-100.0, 35.0], [-100.0, 37.0]], distance_miles=140.0)
    east = -100.0 + 3 / (MILES_PER_DEGREE * math.cos(math.radians(36.0)))  # 3 miles east

    position = line.locate(36.0, east, max_offset_miles=5)

    assert position is not None
    assert position.offset_miles == pytest.approx(3.0, rel=1e-3)
    assert position.mile == pytest.approx(70.0, abs=0.1)


def test_points_outside_the_corridor_are_not_placed() -> None:
    line = RouteLine([[-100.0, 35.0], [-100.0, 37.0]], distance_miles=140.0)
    east = -100.0 + 6 / (MILES_PER_DEGREE * math.cos(math.radians(36.0)))

    assert line.locate(36.0, east, max_offset_miles=5) is None
    assert line.locate(36.0, east, max_offset_miles=6.5) is not None


def test_points_beyond_the_ends_project_to_the_ends() -> None:
    line = RouteLine([[-100.0, 35.0], [-100.0, 36.0]], distance_miles=70.0)

    before = line.locate(35.0 - 2 / MILES_PER_DEGREE, -100.0, max_offset_miles=5)
    after = line.locate(36.0 + 2 / MILES_PER_DEGREE, -100.0, max_offset_miles=5)

    assert before is not None and before.mile == 0 and before.offset_miles == pytest.approx(2)
    assert after is not None and after.mile == pytest.approx(70.0)


def test_route_passing_a_point_twice_uses_the_closest_pass() -> None:
    # Out along lat 36, back along lat 36.05 (~3.5 mi north). A point 1 mile north of the
    # outbound leg is placed on the outbound leg.
    line = RouteLine(
        [[-100.0, 36.0], [-99.0, 36.0], [-99.0, 36.05], [-100.0, 36.05]], distance_miles=1.0
    )
    position = line.locate(36.0 + 1 / MILES_PER_DEGREE, -99.5, max_offset_miles=5)

    assert position is not None
    assert position.offset_miles == pytest.approx(1.0, rel=1e-3)
    assert position.mile < 0.5  # first half of the trip


def test_route_needs_two_points() -> None:
    with pytest.raises(ValueError):
        RouteLine([[-100.0, 35.0]], distance_miles=0)


def test_grid_search_matches_brute_force() -> None:
    """The grid must never miss the true nearest segment."""
    rng = random.Random(7)
    coords = [[-100.0, 35.0]]
    for _ in range(400):  # meandering route, ~0.5-3 mile steps
        lon, lat = coords[-1]
        coords.append([lon + rng.uniform(-0.01, 0.04), lat + rng.uniform(-0.03, 0.03)])
    line = RouteLine(coords, distance_miles=500)
    kx = lambda lat: MILES_PER_DEGREE * math.cos(math.radians(lat))  # noqa: E731

    def brute(lat: float, lon: float) -> float:
        best = math.inf
        for (lat1, lon1), (lat2, lon2) in zip(line.points, line.points[1:], strict=False):
            ax, ay = (lon1 - lon) * kx(lat), (lat1 - lat) * MILES_PER_DEGREE
            bx, by = (lon2 - lon) * kx(lat), (lat2 - lat) * MILES_PER_DEGREE
            dx, dy = bx - ax, by - ay
            ll = dx * dx + dy * dy
            t = 0 if ll == 0 else min(1, max(0, -(ax * dx + ay * dy) / ll))
            best = min(best, math.hypot(ax + t * dx, ay + t * dy))
        return best

    lats = [p[0] for p in line.points]
    lons = [p[1] for p in line.points]
    for _ in range(300):
        lat = rng.uniform(min(lats) - 0.3, max(lats) + 0.3)
        lon = rng.uniform(min(lons) - 0.3, max(lons) + 0.3)
        expected = brute(lat, lon)
        position = line.locate(lat, lon, max_offset_miles=15)
        if expected <= 15:
            assert position is not None
            assert position.offset_miles == pytest.approx(expected, abs=1e-9)
        else:
            assert position is None


def test_dense_geometry_is_thinned_without_losing_mileage() -> None:
    """A tight 2-mile-radius quarter circle sampled every ~0.01 mile, then a straight run."""
    centre_lat, centre_lon = 36.0, -100.0
    kx = MILES_PER_DEGREE * math.cos(math.radians(centre_lat))
    coords = []
    for i in range(315):  # arc length = 2 * pi/2 = 3.14 miles
        angle = (math.pi / 2) * i / 314
        coords.append(
            [
                centre_lon + 2 * math.cos(angle) / kx,
                centre_lat + 2 * math.sin(angle) / MILES_PER_DEGREE,
            ]
        )
    coords.append([centre_lon - 10 / kx, centre_lat + 2 / MILES_PER_DEGREE])  # 10 miles west
    full = RouteLine(coords, distance_miles=13.1416)

    assert len(full.points) < 20  # 316 input points
    assert full.geometric_miles == pytest.approx(math.pi + 10, abs=0.01)

    # A point on the arc (45 degrees) and the end of the arc.
    on_arc = full.locate(
        centre_lat + 2 * math.sin(math.pi / 4) / MILES_PER_DEGREE,
        centre_lon + 2 * math.cos(math.pi / 4) / kx,
        max_offset_miles=1,
    )
    arc_end = full.locate(centre_lat + 2 / MILES_PER_DEGREE, centre_lon, max_offset_miles=1)

    assert on_arc is not None and arc_end is not None
    assert on_arc.offset_miles < 0.1  # thinned chord stays close to the curve
    assert on_arc.mile == pytest.approx(math.pi / 2, abs=0.1)
    assert arc_end.mile == pytest.approx(math.pi, abs=0.01)
