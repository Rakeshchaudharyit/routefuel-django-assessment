"""POST /api/v1/routes/optimize/ end to end: M2 route (OSRM mocked) + M1 stations + M3 optimiser.

The route is a synthetic straight line along latitude 35.2 from (35.2, -101.8) in Texas to
(35.2, -90.2) in Arkansas, with the provider distance set to 700 miles. Station longitudes are
chosen so their scaled mile markers land on round numbers.
"""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal
from typing import Any

import httpx
import pytest
from django.conf import settings
from django.core.cache import cache
from django.urls import reverse
from rest_framework.test import APIClient

from apps.fuel.models import FuelStation, GeolocationAccuracy, GeolocationSource
from apps.routing import services
from apps.routing.providers import METERS_PER_MILE, OsrmProvider

URL = "/api/v1/routes/optimize/"
LAT = 35.2
WEST, EAST = -101.8, -90.2
ROUTE_MILES = 700.0
START = {"latitude": LAT, "longitude": WEST}
FINISH = {"latitude": LAT, "longitude": EAST}


def lon_at(mile: float) -> float:
    return WEST + (EAST - WEST) * mile / ROUTE_MILES


GEOMETRY = {
    "type": "LineString",
    "coordinates": [[round(WEST + (EAST - WEST) * i / 116, 6), LAT] for i in range(117)],
}


class FakeOsrm:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        route = {
            "distance": ROUTE_MILES * METERS_PER_MILE,
            "duration": 36000.0,
            "geometry": GEOMETRY,
        }
        return httpx.Response(200, json={"code": "Ok", "routes": [route]})

    def provider(self) -> OsrmProvider:
        return OsrmProvider(
            settings.ROUTING_BASE_URL,
            timeout=5,
            user_agent="t",
            transport=httpx.MockTransport(self.handler),
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


def make_station(
    opis_id: int,
    price: str,
    *,
    mile: float | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
    uncertainty: float = 1.0,
    name: str | None = None,
) -> FuelStation:
    if mile is not None:
        latitude, longitude = LAT, lon_at(mile)
    resolved = latitude is not None
    return FuelStation.objects.create(
        opis_id=opis_id,
        name=name or f"STOP {opis_id}",
        address=f"I-40, EXIT {opis_id}",
        city=f"Town {opis_id}",
        state="OK",
        rack_id=1,
        retail_price=Decimal(price),
        max_retail_price=Decimal(price),
        latitude=latitude,
        longitude=longitude,
        geolocation_source=GeolocationSource.CENSUS_GAZETTEER_PLACES_2010 if resolved else "",
        geolocation_accuracy=GeolocationAccuracy.CITY
        if resolved
        else GeolocationAccuracy.UNRESOLVED,
        location_uncertainty_miles=uncertainty if resolved else None,
    )


@pytest.fixture
def stations(db: None) -> None:
    make_station(1, "3.50", mile=150)
    make_station(2, "3.10", mile=350)
    make_station(3, "3.30", mile=600)
    make_station(4, "2.00", latitude=LAT + 50 / 69.09, longitude=lon_at(300))  # 50 mi off route
    make_station(5, "1.00")  # unresolved: no coordinates, never a candidate


@pytest.fixture
def client() -> APIClient:
    return APIClient()


def post(client: APIClient, **body: Any) -> Any:
    return client.post(URL, {"start": START, "finish": FINISH, **body}, format="json")


def test_url() -> None:
    assert reverse("v1:routes-optimize") == URL


# --- successful plans ------------------------------------------------------------------


def test_default_vehicle_plan(client: APIClient, osrm: FakeOsrm, stations: None) -> None:
    response = post(client)

    assert response.status_code == 200, response.content
    body = response.json()
    assert body["route"]["distance_miles"] == 700.0
    assert body["route"]["geometry"] == GEOMETRY
    assert body["origin"]["state"] == "TX" and body["destination"]["state"] == "AR"
    assert body["vehicle"] == {
        "range_miles": 500.0,
        "mpg": 10.0,
        "tank_capacity_gallons": "50.000",
        "starting_fuel_gallons": "50.000",
        "starting_fuel_price_per_gallon": None,
    }
    # 70 gal needed, 50 in the tank. Cheapest fuel that fits: 20 gal at station 2 ($3.10).
    plan = body["fuel_plan"]
    assert plan["currency"] == "USD"
    (stop,) = plan["stops"]
    assert stop["station"]["opis_id"] == 2
    assert stop["route_mile"] == pytest.approx(350.0, abs=0.5)
    assert stop["price_per_gallon"] == "3.100"
    assert stop["gallons"] == "20.000"
    assert stop["cost"] == "62.00"
    assert stop["fuel_on_arrival_gallons"] == "15.000"
    assert stop["fuel_on_departure_gallons"] == "35.000"
    assert plan["summary"] == {
        "number_of_stops": 1,
        "total_gallons_consumed": "70.000",
        "starting_fuel_used_gallons": "50.000",
        "total_gallons_purchased": "20.000",
        "total_purchase_cost": "62.00",
        "fuel_remaining_at_destination_gallons": "0.000",
        "starting_fuel_value": None,
        "estimated_total_fuel_cost": None,
        # Added in M4: say explicitly why the whole-trip cost is missing.
        "estimated_total_fuel_cost_status": "unavailable",
        "cost_note": (
            "Whole-trip fuel cost is unavailable: 50.000 gal of starting fuel were used and "
            "starting_fuel_price_per_gallon was not provided. total_purchase_cost covers only "
            "fuel bought at the recommended stops."
        ),
    }
    assert plan["stop_policy"] is None
    assert plan["candidates"] == {
        "corridor_miles": 5.0,
        "stations_in_search_area": 3,
        "stations_on_route": 3,
    }
    assert body["meta"]["routing_requests"] == 1
    assert set(body["meta"]["timings_ms"]) == {"route", "station_matching", "optimization"}


def test_stops_are_labelled_approximate(client: APIClient, osrm: FakeOsrm, stations: None) -> None:
    (stop,) = post(client).json()["fuel_plan"]["stops"]

    assert stop["location"] == {
        "accuracy": "city",
        "source": "census_gazetteer_places_2010",
        "approximate": True,
        "uncertainty_miles": 1.0,
        "distance_from_route_miles": 0.0,
    }


def test_low_starting_fuel_needs_two_stops(
    client: APIClient, osrm: FakeOsrm, stations: None
) -> None:
    body = post(client, vehicle={"starting_fuel_gallons": 20}).json()

    stops = body["fuel_plan"]["stops"]
    assert [(s["station"]["opis_id"], s["gallons"], s["cost"]) for s in stops] == [
        (1, "15.000", "52.50"),  # just enough to reach the cheaper station 2
        (2, "35.000", "108.50"),
    ]
    assert [s["route_mile"] for s in stops] == sorted(s["route_mile"] for s in stops)
    summary = body["fuel_plan"]["summary"]
    assert summary["total_purchase_cost"] == "161.00"
    assert summary["total_gallons_purchased"] == "50.000"
    assert summary["starting_fuel_used_gallons"] == "20.000"


def test_starting_fuel_value_when_price_given(
    client: APIClient, osrm: FakeOsrm, stations: None
) -> None:
    body = post(client, vehicle={"starting_fuel_price_per_gallon": "3.199"}).json()

    summary = body["fuel_plan"]["summary"]
    assert body["vehicle"]["starting_fuel_price_per_gallon"] == "3.199"
    assert summary["starting_fuel_value"] == "159.95"  # 50 gal x 3.199
    assert summary["estimated_total_fuel_cost"] == "221.95"  # + 62.00 bought


def test_short_trip_on_starting_fuel(client: APIClient, osrm: FakeOsrm, stations: None) -> None:
    body = post(client, vehicle={"range_miles": 800}).json()  # 80 gal tank, full

    assert body["fuel_plan"]["stops"] == []
    assert body["fuel_plan"]["summary"]["fuel_remaining_at_destination_gallons"] == "10.000"
    assert body["fuel_plan"]["summary"]["total_purchase_cost"] == "0.00"


def test_unresolved_and_far_stations_are_never_used(
    client: APIClient, osrm: FakeOsrm, stations: None
) -> None:
    # Big tank, 15 gal start: would buy everything at $2.00 / $1.00 if those were candidates.
    body = post(client, vehicle={"starting_fuel_gallons": 15, "range_miles": 1000}).json()

    used = {s["station"]["opis_id"] for s in body["fuel_plan"]["stops"]}
    assert used == {1, 2}
    assert body["fuel_plan"]["candidates"]["stations_on_route"] == 3


def test_uncertainty_widens_the_corridor(client: APIClient, osrm: FakeOsrm, db: None) -> None:
    offset = 8 / 69.09  # 8 miles north of the line
    make_station(10, "3.00", latitude=LAT + offset, longitude=lon_at(300), uncertainty=1.0)
    make_station(11, "3.00", latitude=LAT + offset, longitude=lon_at(320), uncertainty=4.0)

    body = post(client).json()

    (stop,) = body["fuel_plan"]["stops"]
    assert stop["station"]["opis_id"] == 11  # 8 <= 5 + 4; station 10 needs 8 <= 5 + 1
    assert stop["location"]["distance_from_route_miles"] == pytest.approx(8.0, abs=0.05)
    assert body["fuel_plan"]["candidates"]["stations_on_route"] == 1


# --- infeasible plans --------------------------------------------------------------------


def test_no_stations_in_range(client: APIClient, osrm: FakeOsrm, db: None) -> None:
    response = post(client)

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "no_feasible_fuel_plan"
    assert error["details"] == {
        "from_mile": 0.0,
        "to_mile": 700.0,
        "gap_miles": 700.0,
        "max_reach_miles": 500.0,
    }


def test_gap_longer_than_range(client: APIClient, osrm: FakeOsrm, stations: None) -> None:
    response = post(client, vehicle={"range_miles": 200, "mpg": 10})  # 20 gal tank

    error = response.json()["error"]
    assert response.status_code == 422
    assert error["code"] == "no_feasible_fuel_plan"
    assert error["details"]["from_mile"] == pytest.approx(350.0, abs=0.5)
    assert error["details"]["gap_miles"] == pytest.approx(250.0, abs=0.5)


def test_insufficient_starting_fuel(client: APIClient, osrm: FakeOsrm, stations: None) -> None:
    response = post(client, vehicle={"starting_fuel_gallons": 10})  # 100 mi; first stop at 150

    error = response.json()["error"]
    assert error["code"] == "no_feasible_fuel_plan"
    assert "origin" in error["message"]
    assert error["details"]["max_reach_miles"] == 100.0


# --- routing reuse -----------------------------------------------------------------------


def test_route_cache_is_shared_and_reused(
    client: APIClient, osrm: FakeOsrm, stations: None
) -> None:
    first = post(client).json()
    second = post(client, vehicle={"starting_fuel_gallons": 20}).json()
    plain = client.post("/api/v1/routes/", {"start": START, "finish": FINISH}, format="json").json()

    assert len(osrm.requests) == 1
    assert first["meta"]["cached"] is False and first["meta"]["routing_requests"] == 1
    assert second["meta"]["cached"] is True and second["meta"]["routing_requests"] == 0
    assert plain["meta"]["cached"] is True
    assert "fuel_plan" not in plain and "timings_ms" not in plain["meta"]  # M2 unchanged


def test_location_errors_make_no_routing_request(
    client: APIClient, osrm: FakeOsrm, db: None
) -> None:
    response = client.post(URL, {"start": "Toronto, ON", "finish": FINISH}, format="json")

    assert response.json()["error"]["code"] == "location_outside_us"
    assert osrm.requests == []


# --- validation --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("vehicle", "errors"),
    [
        ({"range_miles": 0}, {"range_miles": ["Must be greater than 0 and at most 5000."]}),
        ({"mpg": -1}, {"mpg": ["Must be greater than 0 and at most 200."]}),
        ({"mpg": "10"}, {"mpg": ["A number is required."]}),
        ({"range_miles": True}, {"range_miles": ["A number is required."]}),
        (
            {"starting_fuel_gallons": 60},
            {
                "starting_fuel_gallons": [
                    "Must be between 0 and the tank capacity (50 gallons = range_miles / mpg)."
                ]
            },
        ),
        ({"starting_fuel_gallons": -1}, None),
        ({"starting_fuel_price_per_gallon": "abc"}, None),
        ({"starting_fuel_price_per_gallon": 0.1}, None),
        ({"starting_fuel_price_per_gallon": "3.123456789"}, None),
        ({"tank": 50}, {"non_field_errors": ["Unexpected keys: tank."]}),
    ],
)
def test_invalid_vehicle(
    client: APIClient, osrm: FakeOsrm, vehicle: dict[str, Any], errors: dict[str, Any] | None
) -> None:
    response = post(client, vehicle=vehicle)

    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "invalid"
    assert set(error["details"]) == {"vehicle"}
    if errors is not None:
        assert error["details"]["vehicle"] == errors
    assert osrm.requests == []


@pytest.mark.parametrize("vehicle", [None, [], "500"])
def test_vehicle_must_be_an_object(client: APIClient, osrm: FakeOsrm, vehicle: Any) -> None:
    response = post(client, vehicle=vehicle)

    assert response.status_code == 400
    assert "vehicle" in response.json()["error"]["details"]


def test_missing_locations(client: APIClient, osrm: FakeOsrm) -> None:
    response = client.post(URL, {"vehicle": {}}, format="json")

    assert response.status_code == 400
    assert set(response.json()["error"]["details"]) == {"start", "finish"}


@pytest.mark.parametrize("method", ["get", "put", "patch", "delete"])
def test_unsupported_methods(client: APIClient, method: str) -> None:
    response = getattr(client, method)(URL)

    assert response.status_code == 405
    assert response.json()["error"]["code"] == "method_not_allowed"


def test_query_count(
    client: APIClient, osrm: FakeOsrm, stations: None, django_assert_max_num_queries: Any
) -> None:
    post(client)  # warm the route cache (LocMem: no DB queries)
    with django_assert_max_num_queries(2):  # uncertainty aggregate + one station query
        assert post(client).status_code == 200
