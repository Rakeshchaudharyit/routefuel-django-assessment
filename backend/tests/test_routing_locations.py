from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from django.core.cache import cache, caches
from django.core.management import call_command
from django.db import DatabaseError, connection
from django.test import override_settings

from apps.fuel.constants import US_STATE_CODES
from apps.routing import services
from apps.routing.geography import (
    US_STATE_NAMES,
    BoundaryDataError,
    UsBoundary,
    get_us_boundary,
    normalise_state,
)
from apps.routing.locations import (
    CoordinateQuery,
    LocationError,
    PlaceQuery,
    resolve_location,
)
from apps.routing.providers import METERS_PER_MILE, Coordinate, OsrmProvider, Route, RouteNotFound


def test_state_names_cover_exactly_the_m1_state_codes() -> None:
    assert set(US_STATE_NAMES) == US_STATE_CODES


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("TX", "TX"),
        ("tx", "TX"),
        ("Texas", "TX"),
        ("  new   york ", "NY"),
        ("District of Columbia", "DC"),
        ("D.C.", "DC"),
        ("ON", None),
        ("PR", None),
        ("Texass", None),
    ],
)
def test_normalise_state(raw: str, expected: str | None) -> None:
    assert normalise_state(raw) == expected


@pytest.mark.parametrize(
    ("latitude", "longitude", "state"),
    [
        (32.7767, -96.7970, "TX"),  # Dallas
        (42.3314, -83.0458, "MI"),  # Detroit (Windsor, ON is ~2 km south across the river)
        (31.3404, -110.9343, "AZ"),  # Nogales, AZ
        (61.2181, -149.9003, "AK"),  # Anchorage
        (21.3069, -157.8583, "HI"),  # Honolulu
        (24.5551, -81.7800, "FL"),  # Key West
        (38.8977, -77.0365, "DC"),  # White House
        (42.3149, -83.0364, None),  # Windsor, ON
        (31.3000, -110.9400, None),  # Nogales, Sonora
        (49.2827, -123.1207, None),  # Vancouver, BC
        (35.0, -70.0, None),  # Atlantic Ocean
        (0.0, 0.0, None),
    ],
)
def test_state_at(latitude: float, longitude: float, state: str | None) -> None:
    assert get_us_boundary().state_at(latitude, longitude) == state


def test_polygon_holes_are_excluded(tmp_path: Path) -> None:
    square = [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]
    hole = [[4, 4], [6, 4], [6, 6], [4, 6], [4, 4]]
    path = tmp_path / "b.geojson"
    path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {"state": "XX"},
                        "geometry": {"type": "MultiPolygon", "coordinates": [[square, hole]]},
                    }
                ],
            }
        )
    )
    boundary = UsBoundary.from_file(path)

    assert boundary.state_at(2, 2) == "XX"
    assert boundary.state_at(5, 5) is None
    assert boundary.state_at(20, 20) is None


@pytest.mark.parametrize(
    "content", ["not json", '{"features": []}', '{"features": [{"properties": {}}]}']
)
def test_bad_boundary_file(tmp_path: Path, content: str) -> None:
    path = tmp_path / "b.geojson"
    path.write_text(content)

    with pytest.raises(BoundaryDataError):
        UsBoundary.from_file(path)


def test_missing_boundary_file(tmp_path: Path) -> None:
    with pytest.raises(BoundaryDataError, match="not found"):
        UsBoundary.from_file(tmp_path / "missing.geojson")


def test_resolve_place_uses_census_internal_point() -> None:
    location = resolve_location(PlaceQuery("Atlanta", "GA"))

    assert (location.latitude, location.longitude) == (33.762909, -84.422675)
    assert location.label == "Atlanta, GA"


def test_resolve_coordinates_keeps_input_point() -> None:
    location = resolve_location(CoordinateQuery(33.749, -84.388))

    assert (location.latitude, location.longitude, location.state) == (33.749, -84.388, "GA")


def test_ambiguous_candidates_are_listed() -> None:
    with pytest.raises(LocationError) as info:
        resolve_location(PlaceQuery("Cottonwood", "AZ"))

    assert info.value.code == "ambiguous_location"
    assert len(info.value.details["candidates"]) == 2


def test_miles_conversion_constant_is_the_international_mile() -> None:
    route = Route(distance_meters=160934.4, duration_seconds=5400, geometry={}, provider="x")

    assert METERS_PER_MILE == 1609.344
    assert route.distance_miles == pytest.approx(100.0, abs=1e-12)
    assert route.duration_minutes == 90.0


def test_provider_timeout_is_configured() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(request.extensions["timeout"])
        return httpx.Response(400, json={"code": "NoRoute"})

    provider = OsrmProvider(
        "https://osrm.test/", timeout=7, user_agent="ua", transport=httpx.MockTransport(handler)
    )
    with pytest.raises(RouteNotFound):
        provider.route(Coordinate(32.0, -96.0), Coordinate(33.0, -84.0))

    assert seen == {"connect": 5.0, "read": 7, "write": 7, "pool": 7}


# --- database cache -----------------------------------------------------------------

DB_CACHE = {
    "default": {
        "BACKEND": "django.core.cache.backends.db.DatabaseCache",
        "LOCATION": "routefuel_cache",
    }
}


@pytest.mark.django_db
def test_database_cache_table_and_roundtrip() -> None:
    with override_settings(CACHES=DB_CACHE):
        call_command("createcachetable", verbosity=0)
        db_cache = caches.create_connection("default")
        db_cache.set("route:test", {"geometry": {"coordinates": [[1.0, 2.0]]}}, 60)

        assert "routefuel_cache" in connection.introspection.table_names()
        assert db_cache.get("route:test") == {"geometry": {"coordinates": [[1.0, 2.0]]}}


def test_cache_errors_do_not_break_routing(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(*args: object, **kwargs: object) -> None:
        raise DatabaseError("no such table: routefuel_cache")

    monkeypatch.setattr(cache, "get", broken)
    monkeypatch.setattr(cache, "set", broken)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "code": "Ok",
                "routes": [
                    {
                        "distance": 1000.0,
                        "duration": 60.0,
                        "geometry": {"type": "LineString", "coordinates": [[-96, 32], [-84, 33]]},
                    }
                ],
            },
        )

    provider = OsrmProvider(
        "https://osrm.test", timeout=5, user_agent="ua", transport=httpx.MockTransport(handler)
    )
    plan = services.plan_route(
        PlaceQuery("Dallas", "TX"), PlaceQuery("Atlanta", "GA"), provider=provider
    )

    assert plan.cached is False
    assert plan.route.distance_meters == 1000.0
