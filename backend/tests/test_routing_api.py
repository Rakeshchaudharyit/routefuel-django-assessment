"""POST /api/v1/routes/ — end to end through Django, with OSRM replaced by httpx.MockTransport.

Location resolution uses the real reference data in ``backend/data/reference``.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest
from django.conf import settings
from django.core.cache import cache
from django.urls import resolve, reverse
from rest_framework.test import APIClient

from apps.routing import services
from apps.routing.providers import OsrmProvider
from apps.routing.views import RouteView

ROUTES_URL = "/api/v1/routes/"

# distance/duration are the values the public OSRM server returned for Dallas -> Atlanta
# on 2026-10-21 (overview=false). The geometry below is a short hand-written line.
DALLAS_ATLANTA_METERS = 1259435.7
DALLAS_ATLANTA_SECONDS = 50903.2
GEOMETRY = {
    "type": "LineString",
    "coordinates": [[-96.765503, 32.794176], [-90.18, 32.30], [-84.422675, 33.762909]],
}


def osrm_ok(
    distance: float = DALLAS_ATLANTA_METERS,
    duration: float = DALLAS_ATLANTA_SECONDS,
    geometry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "code": "Ok",
        "routes": [
            {
                "distance": distance,
                "duration": duration,
                "geometry": geometry or GEOMETRY,
                "legs": [],
                "weight": duration,
                "weight_name": "routability",
            }
        ],
        "waypoints": [],
    }


Handler = Callable[[httpx.Request], httpx.Response]


@dataclass
class FakeOsrm:
    handler: Handler = field(default=lambda request: httpx.Response(200, json=osrm_ok()))
    requests: list[httpx.Request] = field(default_factory=list)

    def respond(self, status: int = 200, body: Any = None, *, text: str | None = None) -> None:
        if text is not None:
            self.handler = lambda request: httpx.Response(status, text=text)
        else:
            self.handler = lambda request: httpx.Response(status, json=body)

    def raise_(self, exc: Exception) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise exc

        self.handler = handler

    def _dispatch(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.handler(request)

    def provider(self) -> OsrmProvider:
        return OsrmProvider(
            settings.ROUTING_BASE_URL,
            timeout=settings.ROUTING_TIMEOUT,
            user_agent=settings.ROUTING_USER_AGENT,
            transport=httpx.MockTransport(self._dispatch),
        )


@pytest.fixture(autouse=True)
def clear_cache() -> Iterator[None]:
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def osrm(monkeypatch: pytest.MonkeyPatch) -> FakeOsrm:
    fake = FakeOsrm()
    monkeypatch.setattr(services, "get_routing_provider", fake.provider)
    return fake


@pytest.fixture
def client() -> APIClient:
    return APIClient()


def post(client: APIClient, body: Any) -> Any:
    return client.post(ROUTES_URL, body, format="json")


def assert_error(response: Any, status: int, code: str) -> dict[str, Any]:
    assert response.status_code == status, response.content
    assert response["Content-Type"] == "application/json"
    body = response.json()
    assert set(body) == {"error"}
    assert set(body["error"]) == {"code", "message", "details"}
    assert body["error"]["code"] == code
    assert isinstance(body["error"]["message"], str) and body["error"]["message"]
    return body["error"]


CITY_BODY = {"start": "Dallas, TX", "finish": "Atlanta, GA"}
COORD_BODY = {
    "start": {"latitude": 32.7767, "longitude": -96.7970},
    "finish": {"latitude": 33.7490, "longitude": -84.3880},
}


# --- URLs ---------------------------------------------------------------------------


def test_routes_url_is_versioned() -> None:
    assert reverse("v1:routes") == ROUTES_URL
    assert resolve(ROUTES_URL).func.view_class is RouteView


# --- successful requests ------------------------------------------------------------


def test_city_state_input_resolves_and_returns_route(client: APIClient, osrm: FakeOsrm) -> None:
    response = post(client, CITY_BODY)

    assert response.status_code == 200
    body = response.json()
    # Census 2010 internal points for the two places.
    assert body["origin"] == {
        "label": "Dallas, TX",
        "latitude": 32.794176,
        "longitude": -96.765503,
        "state": "TX",
        "source": "census_place",
    }
    assert body["destination"]["label"] == "Atlanta, GA"
    assert body["destination"]["latitude"] == 33.762909
    assert body["destination"]["longitude"] == -84.422675
    assert body["route"]["distance_miles"] == 782.58
    assert body["route"]["duration_minutes"] == 848.4
    assert body["meta"] == {
        "provider": "osrm",
        "attribution": OsrmProvider.attribution,
        "cached": False,
        "routing_requests": 1,
    }
    assert "fuel_stops" not in body and "total_fuel_cost" not in body


@pytest.mark.parametrize(
    ("start", "label"),
    [
        ("dallas, tx", "Dallas, TX"),
        ("  Dallas ,  Texas ", "Dallas, TX"),
        ("St. Louis, MO", "St. Louis, MO"),
        ("Saint Louis, Missouri", "St. Louis, MO"),
        ("Indianapolis, IN", "Indianapolis, IN"),
    ],
)
def test_city_names_are_normalised(
    client: APIClient, osrm: FakeOsrm, start: str, label: str
) -> None:
    response = post(client, {"start": start, "finish": "Atlanta, GA"})

    assert response.status_code == 200
    assert response.json()["origin"]["label"] == label


def test_coordinate_input(client: APIClient, osrm: FakeOsrm) -> None:
    response = post(client, COORD_BODY)

    assert response.status_code == 200
    body = response.json()
    assert body["origin"] == {
        "label": "32.77670, -96.79700",
        "latitude": 32.7767,
        "longitude": -96.797,
        "state": "TX",
        "source": "coordinates",
    }
    assert body["destination"]["state"] == "GA"
    (request,) = osrm.requests
    assert request.url.path == "/route/v1/driving/-96.797000,32.776700;-84.388000,33.749000"


def test_mixed_city_and_coordinate_input(client: APIClient, osrm: FakeOsrm) -> None:
    response = post(client, {"start": "Dallas, TX", "finish": COORD_BODY["finish"]})

    assert response.status_code == 200
    assert response.json()["destination"]["source"] == "coordinates"


def test_integer_coordinates_are_accepted(client: APIClient, osrm: FakeOsrm) -> None:
    response = post(
        client,
        {"start": {"latitude": 33, "longitude": -97}, "finish": {"latitude": 34, "longitude": -84}},
    )

    assert response.status_code == 200


def test_osrm_request_shape(client: APIClient, osrm: FakeOsrm) -> None:
    post(client, CITY_BODY)

    (request,) = osrm.requests
    assert request.method == "GET"
    assert str(request.url).startswith("https://router.example.test/route/v1/driving/")
    assert request.url.path == "/route/v1/driving/-96.765503,32.794176;-84.422675,33.762909"
    assert dict(request.url.params) == {
        "overview": "full",
        "geometries": "geojson",
        "steps": "false",
        "alternatives": "false",
        "annotations": "false",
    }
    assert request.headers["User-Agent"] == "RouteFuel-tests/1.0"


def test_response_geometry_is_geojson_linestring(client: APIClient, osrm: FakeOsrm) -> None:
    geometry = post(client, CITY_BODY).json()["route"]["geometry"]

    assert geometry == GEOMETRY
    assert geometry["type"] == "LineString"
    assert len(geometry["coordinates"]) >= 2
    for lon, lat in geometry["coordinates"]:
        assert -180 <= lon <= 180 and -90 <= lat <= 90


@pytest.mark.parametrize(
    ("meters", "miles"),
    [(1609.344, 1.0), (DALLAS_ATLANTA_METERS, 782.58), (4496847.5, 2794.21), (0.0, 0.0)],
)
def test_distance_is_converted_to_miles(
    client: APIClient, osrm: FakeOsrm, meters: float, miles: float
) -> None:
    osrm.respond(200, osrm_ok(distance=meters, duration=3600))

    route = post(client, CITY_BODY).json()["route"]

    assert route["distance_miles"] == miles
    assert route["duration_minutes"] == 60.0


# --- input validation (400) ---------------------------------------------------------


@pytest.mark.parametrize("missing", ["start", "finish"])
def test_missing_location(client: APIClient, osrm: FakeOsrm, missing: str) -> None:
    body = {k: v for k, v in CITY_BODY.items() if k != missing}

    error = assert_error(post(client, body), 400, "invalid")

    assert error["details"] == {missing: ["This field is required."]}
    assert osrm.requests == []


def test_empty_body(client: APIClient, osrm: FakeOsrm) -> None:
    error = assert_error(post(client, {}), 400, "invalid")

    assert set(error["details"]) == {"start", "finish"}


@pytest.mark.parametrize("latitude", [90.0001, -91, 1e9])
def test_invalid_latitude(client: APIClient, osrm: FakeOsrm, latitude: float) -> None:
    body = {**COORD_BODY, "start": {"latitude": latitude, "longitude": -96.797}}

    error = assert_error(post(client, body), 400, "invalid")

    assert error["details"] == {"start": {"latitude": ["Latitude must be between -90 and 90."]}}
    assert osrm.requests == []


@pytest.mark.parametrize("longitude", [180.5, -181])
def test_invalid_longitude(client: APIClient, osrm: FakeOsrm, longitude: float) -> None:
    body = {**COORD_BODY, "finish": {"latitude": 33.749, "longitude": longitude}}

    error = assert_error(post(client, body), 400, "invalid")

    assert error["details"] == {
        "finish": {"longitude": ["Longitude must be between -180 and 180."]}
    }


@pytest.mark.parametrize(
    ("start", "expected"),
    [
        ({"latitude": "32.7", "longitude": -96.8}, {"latitude": ["A number is required."]}),
        ({"latitude": True, "longitude": -96.8}, {"latitude": ["A number is required."]}),
        ({"longitude": -96.8}, {"latitude": ["This field is required."]}),
        (
            {"latitude": 32.7, "longitude": -96.8, "zoom": 3},
            {"non_field_errors": ["Unexpected keys: zoom."]},
        ),
    ],
)
def test_malformed_coordinate_objects(
    client: APIClient, osrm: FakeOsrm, start: dict[str, Any], expected: dict[str, Any]
) -> None:
    error = assert_error(post(client, {**COORD_BODY, "start": start}), 400, "invalid")

    assert error["details"] == {"start": expected}


@pytest.mark.parametrize(
    ("start", "message"),
    [
        ("", "This field may not be blank."),
        ("   ", "This field may not be blank."),
        ("Dallas", 'Use the format "City, ST" (for example "Dallas, TX").'),
        ("Dallas,", 'Use the format "City, ST" (for example "Dallas, TX").'),
        (", TX", 'Use the format "City, ST" (for example "Dallas, TX").'),
        ("x" * 121 + ", TX", "Ensure this field has no more than 120 characters."),
        (42, 'Expected "City, ST" or an object with "latitude" and "longitude".'),
        ([32.7, -96.8], 'Expected "City, ST" or an object with "latitude" and "longitude".'),
        (None, "This field may not be null."),
    ],
)
def test_malformed_location_values(
    client: APIClient, osrm: FakeOsrm, start: Any, message: str
) -> None:
    error = assert_error(post(client, {**CITY_BODY, "start": start}), 400, "invalid")

    assert error["details"] == {"start": [message]}


def test_non_object_body(client: APIClient, osrm: FakeOsrm) -> None:
    assert_error(post(client, ["Dallas, TX", "Atlanta, GA"]), 400, "invalid")


def test_non_json_body_is_rejected(client: APIClient, osrm: FakeOsrm) -> None:
    response = client.post(ROUTES_URL, "start=Dallas", content_type="text/plain")

    assert_error(response, 415, "unsupported_media_type")


def test_invalid_json_is_rejected(client: APIClient, osrm: FakeOsrm) -> None:
    response = client.post(ROUTES_URL, "{not json", content_type="application/json")

    assert_error(response, 400, "parse_error")


# --- location resolution (422) ------------------------------------------------------


@pytest.mark.parametrize(
    "start",
    [
        {"latitude": 43.6532, "longitude": -79.3832},  # Toronto
        {"latitude": 32.5149, "longitude": -117.0382},  # Tijuana
        {"latitude": 26.0, "longitude": -90.0},  # Gulf of Mexico
        {"latitude": 51.5074, "longitude": -0.1278},  # London
        {"latitude": 18.4655, "longitude": -66.1057},  # San Juan, Puerto Rico
    ],
)
def test_non_us_coordinates_are_rejected(
    client: APIClient, osrm: FakeOsrm, start: dict[str, float]
) -> None:
    error = assert_error(post(client, {**COORD_BODY, "start": start}), 422, "location_outside_us")

    assert error["details"]["field"] == "start"
    assert osrm.requests == []


@pytest.mark.parametrize("start", ["Toronto, ON", "Vancouver, BC", "San Juan, PR", "Hagatna, GU"])
def test_non_us_regions_are_rejected(client: APIClient, osrm: FakeOsrm, start: str) -> None:
    error = assert_error(post(client, {**CITY_BODY, "start": start}), 422, "location_outside_us")

    assert error["details"]["field"] == "start"


def test_ambiguous_city_is_rejected_not_guessed(client: APIClient, osrm: FakeOsrm) -> None:
    # The gazetteer has both "Cottonwood city" and "Cottonwood CDP" in Arizona.
    error = assert_error(
        post(client, {**CITY_BODY, "finish": "Cottonwood, AZ"}), 422, "ambiguous_location"
    )

    details = error["details"]
    assert details["field"] == "finish"
    assert details["state"] == "AZ"
    assert sorted(c["name"] for c in details["candidates"]) == [
        "Cottonwood CDP",
        "Cottonwood city",
    ]
    assert osrm.requests == []


@pytest.mark.parametrize(
    ("start", "detail_key"),
    [("Atlantis, TX", "city"), ("Dallas, ZZ", "state"), ("Dallas, Texass", "state")],
)
def test_unknown_place_or_state(
    client: APIClient, osrm: FakeOsrm, start: str, detail_key: str
) -> None:
    error = assert_error(post(client, {**CITY_BODY, "start": start}), 422, "location_not_found")

    assert error["details"]["field"] == "start"
    assert detail_key in error["details"]


def test_same_start_and_finish(client: APIClient, osrm: FakeOsrm) -> None:
    error = assert_error(
        post(client, {"start": "Dallas, TX", "finish": "dallas, texas"}), 422, "same_location"
    )

    assert error["details"] is None
    assert osrm.requests == []


def test_start_error_is_reported_before_finish(client: APIClient, osrm: FakeOsrm) -> None:
    error = assert_error(
        post(client, {"start": "Atlantis, TX", "finish": "Toronto, ON"}), 422, "location_not_found"
    )

    assert error["details"]["field"] == "start"


# --- provider failures --------------------------------------------------------------


def test_provider_timeout(client: APIClient, osrm: FakeOsrm) -> None:
    osrm.raise_(httpx.ReadTimeout("timed out"))

    assert_error(post(client, CITY_BODY), 504, "routing_timeout")
    assert len(osrm.requests) == 1  # no retry


def test_provider_connection_failure(client: APIClient, osrm: FakeOsrm) -> None:
    osrm.raise_(httpx.ConnectError("connection refused"))

    assert_error(post(client, CITY_BODY), 503, "routing_unavailable")
    assert len(osrm.requests) == 1


@pytest.mark.parametrize(
    ("status", "body", "expected_status", "code"),
    [
        (500, {"message": "boom"}, 503, "routing_unavailable"),
        (502, None, 503, "routing_unavailable"),
        (429, {"message": "Too Many Requests"}, 503, "routing_unavailable"),
        (403, None, 502, "routing_provider_error"),
        (404, None, 502, "routing_provider_error"),
        (400, {"code": "InvalidQuery", "message": "bad"}, 502, "routing_provider_error"),
        (400, {"code": "TooBig", "message": "too big"}, 502, "routing_provider_error"),
    ],
)
def test_provider_http_errors(
    client: APIClient,
    osrm: FakeOsrm,
    status: int,
    body: Any,
    expected_status: int,
    code: str,
) -> None:
    if body is None:
        osrm.respond(status, text="<html>error</html>")
    else:
        osrm.respond(status, body)

    error = assert_error(post(client, CITY_BODY), expected_status, code)

    assert "<html>" not in error["message"]
    assert len(osrm.requests) == 1


@pytest.mark.parametrize("osrm_code", ["NoRoute", "NoSegment"])
def test_no_route(client: APIClient, osrm: FakeOsrm, osrm_code: str) -> None:
    osrm.respond(400, {"code": osrm_code, "message": "Impossible route between points"})

    assert_error(post(client, CITY_BODY), 422, "route_not_found")


def _one_route(**route: Any) -> str:
    return json.dumps({"code": "Ok", "routes": [route]})


def _line(*coordinates: Any) -> dict[str, Any]:
    return {"type": "LineString", "coordinates": list(coordinates)}


@pytest.mark.parametrize(
    "body",
    [
        "not json at all",
        json.dumps({"code": "Ok", "routes": []}),
        json.dumps({"code": "Ok"}),
        json.dumps({"code": "Weird"}),
        json.dumps([1, 2, 3]),
        _one_route(distance=1, duration=1),
        _one_route(distance="far", duration=1, geometry=GEOMETRY),
        _one_route(distance=-5, duration=1, geometry=GEOMETRY),
        _one_route(distance=1, duration=1, geometry="_p~iF~ps|U"),  # encoded polyline
        _one_route(distance=1, duration=1, geometry={"type": "Point", "coordinates": [-96, 32]}),
        _one_route(distance=1, duration=1, geometry=_line([-96.8, 32.8])),
        _one_route(distance=1, duration=1, geometry=_line([-96.8, 32.8], [200, 95])),
        _one_route(distance=1, duration=1, geometry=_line([-96.8, 32.8], ["a", None])),
        _one_route(distance=1, duration=1, geometry=_line([-96.8, 32.8], [-84.4, 33.7, 5])),
    ],
)
def test_malformed_provider_response(client: APIClient, osrm: FakeOsrm, body: str) -> None:
    osrm.respond(200, text=body)

    assert_error(post(client, CITY_BODY), 502, "routing_provider_error")


# --- caching and request count ------------------------------------------------------


def test_repeated_request_is_served_from_cache(client: APIClient, osrm: FakeOsrm) -> None:
    first = post(client, CITY_BODY).json()
    second = post(client, CITY_BODY).json()

    assert len(osrm.requests) == 1
    assert first["meta"]["cached"] is False and first["meta"]["routing_requests"] == 1
    assert second["meta"]["cached"] is True and second["meta"]["routing_requests"] == 0
    assert second["route"] == first["route"]
    assert second["origin"] == first["origin"]


def test_equivalent_inputs_share_cache_entry(client: APIClient, osrm: FakeOsrm) -> None:
    post(client, CITY_BODY)
    post(client, {"start": "dallas, texas", "finish": " Atlanta , ga"})
    # Same point given as coordinates resolves to the same rounded key.
    post(
        client,
        {
            "start": {"latitude": 32.794176, "longitude": -96.765503},
            "finish": "Atlanta, GA",
        },
    )

    assert len(osrm.requests) == 1


def test_reverse_direction_is_a_separate_route(client: APIClient, osrm: FakeOsrm) -> None:
    post(client, CITY_BODY)
    post(client, {"start": "Atlanta, GA", "finish": "Dallas, TX"})

    assert len(osrm.requests) == 2


def test_failures_are_not_cached(client: APIClient, osrm: FakeOsrm) -> None:
    osrm.raise_(httpx.ReadTimeout("timed out"))
    assert post(client, CITY_BODY).status_code == 504

    osrm.respond(200, osrm_ok())
    response = post(client, CITY_BODY)

    assert response.status_code == 200
    assert response.json()["meta"]["cached"] is False
    assert len(osrm.requests) == 2


def test_cache_entry_uses_configured_ttl(
    client: APIClient, osrm: FakeOsrm, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[str, int]] = []
    real_set = cache.set

    def spy(key: str, value: Any, timeout: int) -> None:
        calls.append((key, timeout))
        real_set(key, value, timeout)

    monkeypatch.setattr(services.cache, "set", spy)

    post(client, CITY_BODY)

    ((key, timeout),) = calls
    assert key.startswith("route:v1:")
    assert timeout == settings.ROUTE_CACHE_TTL == 3600


def test_exactly_one_routing_request_per_uncached_route(client: APIClient, osrm: FakeOsrm) -> None:
    for body in (
        CITY_BODY,
        {"start": "Chicago, IL", "finish": "Denver, CO"},
        COORD_BODY,
        CITY_BODY,  # cached
        {"start": "Chicago, IL", "finish": "Denver, CO"},  # cached
    ):
        assert post(client, body).status_code == 200

    assert len(osrm.requests) == 3


# --- methods and error envelope -----------------------------------------------------


@pytest.mark.parametrize("method", ["get", "put", "patch", "delete"])
def test_unsupported_methods(client: APIClient, osrm: FakeOsrm, method: str) -> None:
    response = getattr(client, method)(ROUTES_URL)

    error = assert_error(response, 405, "method_not_allowed")
    assert method.upper() in error["message"]
    assert error["details"] is None
    assert osrm.requests == []
