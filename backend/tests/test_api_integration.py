"""M4: request coalescing, response contract, cost clarity, practical stops, geometry options,
error envelope, CORS and performance regressions."""

from __future__ import annotations

import json
import math
import random
import threading
import time
from decimal import Decimal
from typing import Any

import httpx
import pytest
from django.conf import settings
from django.core.cache import cache
from django.core.management import call_command
from django.db import DatabaseError
from rest_framework.test import APIClient

from apps.core.renderers import RawJSON, RawJSONRenderer
from apps.fuel.models import FuelStation
from apps.optimization.geometry import MILES_PER_DEGREE, simplify
from apps.optimization.optimizer import (
    Candidate,
    InfeasiblePlan,
    Vehicle,
    check_plan,
    optimize,
    reduce_stops,
)
from apps.routing import fuel_plans, services
from apps.routing.locations import CoordinateQuery
from apps.routing.providers import METERS_PER_MILE, OsrmProvider, Route
from tests.test_optimize_api import (  # noqa: F401 — fixtures are used by name
    FINISH,
    GEOMETRY,
    START,
    URL,
    FakeOsrm,
    clear_cache,
    client,
    lon_at,
    make_station,
    osrm,
    stations,
)

D = Decimal


def post(api: APIClient, **body: Any) -> Any:
    return api.post(URL, {"start": START, "finish": FINISH, **body}, format="json")


# --- response contract (what the M5 dashboard relies on) ----------------------------------

TOP_LEVEL = {"origin", "destination", "route", "vehicle", "fuel_plan", "meta"}
LOCATION = {"label", "latitude", "longitude", "state", "source"}
ROUTE = {"distance_miles", "duration_minutes", "geometry", "geometry_detail",
         "geometry_tolerance_meters"}  # fmt: skip
VEHICLE = {"range_miles", "mpg", "tank_capacity_gallons", "starting_fuel_gallons",
           "starting_fuel_price_per_gallon"}  # fmt: skip
FUEL_PLAN = {"currency", "stops", "summary", "stop_policy", "candidates"}
STOP = {"sequence", "station", "location", "route_mile", "price_per_gallon", "gallons", "cost",
        "fuel_on_arrival_gallons", "fuel_on_departure_gallons"}  # fmt: skip
STATION = {"opis_id", "name", "address", "city", "state", "latitude", "longitude"}
STOP_LOCATION = {"accuracy", "source", "approximate", "uncertainty_miles",
                 "distance_from_route_miles"}  # fmt: skip
SUMMARY = {"number_of_stops", "total_gallons_consumed", "starting_fuel_used_gallons",
           "total_gallons_purchased", "total_purchase_cost",
           "fuel_remaining_at_destination_gallons", "starting_fuel_value",
           "estimated_total_fuel_cost", "estimated_total_fuel_cost_status",
           "cost_note"}  # fmt: skip
CANDIDATES = {"corridor_miles", "stations_in_search_area", "stations_on_route"}
META = {"provider", "attribution", "cached", "routing_requests", "timings_ms"}
TIMINGS = {"route", "station_matching", "optimization"}


def test_optimize_response_schema(client: APIClient, osrm: FakeOsrm, stations: None) -> None:
    body = post(client, vehicle={"starting_fuel_gallons": 20}).json()

    assert set(body) == TOP_LEVEL
    assert set(body["origin"]) == set(body["destination"]) == LOCATION
    assert set(body["route"]) == ROUTE
    assert set(body["vehicle"]) == VEHICLE
    assert set(body["fuel_plan"]) == FUEL_PLAN
    assert set(body["fuel_plan"]["summary"]) == SUMMARY
    assert set(body["fuel_plan"]["candidates"]) == CANDIDATES
    assert set(body["meta"]) == META and set(body["meta"]["timings_ms"]) == TIMINGS
    assert len(body["fuel_plan"]["stops"]) == 2
    for stop in body["fuel_plan"]["stops"]:
        assert set(stop) == STOP
        assert set(stop["station"]) == STATION
        assert set(stop["location"]) == STOP_LOCATION
        # Money and gallons are decimal strings with fixed places; miles are numbers.
        assert stop["cost"].count(".") == 1 and len(stop["cost"].split(".")[1]) == 2
        assert len(stop["gallons"].split(".")[1]) == 3
        assert isinstance(stop["route_mile"], float)


def test_routes_response_schema_is_backward_compatible(
    client: APIClient, osrm: FakeOsrm, db: None
) -> None:
    body = client.post("/api/v1/routes/", {"start": START, "finish": FINISH}, format="json").json()

    assert set(body) == {"origin", "destination", "route", "meta"}
    assert set(body["route"]) == ROUTE
    assert set(body["meta"]) == {"provider", "attribution", "cached", "routing_requests"}
    assert body["route"]["geometry"] == GEOMETRY
    assert body["route"]["geometry_detail"] == "full"
    assert body["route"]["geometry_tolerance_meters"] is None


# --- fuel-cost clarity -------------------------------------------------------------------


def test_whole_trip_cost_unavailable_without_starting_price(
    client: APIClient, osrm: FakeOsrm, stations: None
) -> None:
    summary = post(client).json()["fuel_plan"]["summary"]

    assert summary["estimated_total_fuel_cost"] is None
    assert summary["estimated_total_fuel_cost_status"] == "unavailable"
    assert "starting_fuel_price_per_gallon was not provided" in summary["cost_note"]
    assert summary["total_purchase_cost"] == "62.00"


def test_whole_trip_cost_with_starting_price(
    client: APIClient, osrm: FakeOsrm, stations: None
) -> None:
    summary = post(client, vehicle={"starting_fuel_price_per_gallon": 3}).json()["fuel_plan"][
        "summary"
    ]

    assert summary["starting_fuel_value"] == "150.00"
    assert summary["estimated_total_fuel_cost"] == "212.00"
    assert summary["estimated_total_fuel_cost_status"] == "calculated"


def test_whole_trip_cost_with_empty_start_needs_no_price(
    client: APIClient, osrm: FakeOsrm, db: None
) -> None:
    make_station(20, "3.00", mile=0)  # at the origin
    make_station(21, "3.10", mile=400)

    summary = post(client, vehicle={"starting_fuel_gallons": 0}).json()["fuel_plan"]["summary"]

    assert summary["starting_fuel_used_gallons"] == "0.000"
    assert summary["starting_fuel_value"] == "0.00"
    assert summary["total_gallons_purchased"] == "70.000"
    assert summary["estimated_total_fuel_cost"] == summary["total_purchase_cost"]
    assert summary["estimated_total_fuel_cost_status"] == "calculated"


# --- practical-stop policy -----------------------------------------------------------------


@pytest.fixture
def small_top_up(db: None) -> None:
    # Minimum cost: 5 gal at mile 50 ($3.00) + 15 gal at mile 450 ($3.02) = $60.30.
    # One stop instead: 20 gal at $3.02 = $60.40 (+$0.10).
    make_station(30, "3.00", mile=50)
    make_station(31, "3.02", mile=450)


def test_default_plan_keeps_cost_saving_top_up(
    client: APIClient, osrm: FakeOsrm, small_top_up: None
) -> None:
    plan = post(client).json()["fuel_plan"]

    assert [s["station"]["opis_id"] for s in plan["stops"]] == [30, 31]
    assert plan["summary"]["total_purchase_cost"] == "60.30"
    assert plan["stop_policy"] is None


def test_stop_policy_drops_stop_that_saves_too_little(
    client: APIClient, osrm: FakeOsrm, small_top_up: None
) -> None:
    plan = post(client, stop_policy={"min_savings_per_stop": "1.00"}).json()["fuel_plan"]

    assert [s["station"]["opis_id"] for s in plan["stops"]] == [31]
    assert plan["summary"]["total_purchase_cost"] == "60.40"
    assert plan["stop_policy"] == {
        "min_savings_per_stop": "1.00",
        "stops_removed": 1,
        "removed_station_opis_ids": [30],
        "minimum_purchase_cost": "60.30",
        "minimum_cost_number_of_stops": 2,
        "extra_cost": "0.10",
    }


def test_stop_policy_keeps_stop_that_saves_enough(
    client: APIClient, osrm: FakeOsrm, small_top_up: None
) -> None:
    plan = post(client, stop_policy={"min_savings_per_stop": "0.05"}).json()["fuel_plan"]

    assert len(plan["stops"]) == 2
    assert plan["stop_policy"]["stops_removed"] == 0
    assert plan["stop_policy"]["extra_cost"] == "0.00"


@pytest.mark.parametrize(
    "policy", [{"min_savings_per_stop": 0}, {"min_savings_per_stop": "abc"},
               {"min_savings_per_stop": "1.001"}, {"min_savings_per_stop": 5000},
               {"min_savings_per_stop": True}, {}, {"other": 1}, "5.00"],
)  # fmt: skip
def test_invalid_stop_policy(client: APIClient, osrm: FakeOsrm, policy: Any) -> None:
    response = post(client, stop_policy=policy)

    assert response.status_code == 400
    assert set(response.json()["error"]["details"]) == {"stop_policy"}
    assert osrm.requests == []


def test_reduce_stops_properties() -> None:
    """Random instances: always feasible, each removal saved less than the threshold."""
    rng = random.Random(11)
    for _ in range(300):
        distance = rng.uniform(100, 2500)
        candidates = [
            Candidate(i, rng.uniform(0, distance), D(rng.choice(["2.95", "3.00", "3.02", "3.40"])))
            for i in range(rng.randint(1, 25))
        ]
        vehicle = Vehicle(500, 10, rng.choice([0, 25, 50]))
        threshold = D(rng.choice(["0.50", "2.00", "10.00"]))
        try:
            result = reduce_stops(distance, candidates, vehicle, threshold)
        except InfeasiblePlan:
            with pytest.raises(InfeasiblePlan):
                optimize(distance, candidates, vehicle)
            continue
        check_plan(result.plan)
        minimum = result.minimum_cost_plan
        assert minimum.exact_cost == optimize(distance, candidates, vehicle).exact_cost
        assert len(result.plan.purchases) <= len(minimum.purchases)
        assert result.plan.exact_cost >= minimum.exact_cost - D("1e-9")  # float noise on ties
        assert result.plan.exact_cost - minimum.exact_cost < threshold * len(
            result.removed_keys
        ) + D("1e-9")


# --- geometry options ----------------------------------------------------------------------


def test_simplified_geometry_option(client: APIClient, osrm: FakeOsrm, stations: None) -> None:
    full = post(client).json()
    light = post(client, geometry_detail="simplified").json()

    coords = light["route"]["geometry"]["coordinates"]
    assert light["route"]["geometry_detail"] == "simplified"
    assert light["route"]["geometry_tolerance_meters"] == 25.0
    assert light["route"]["geometry"]["type"] == "LineString"
    assert coords[0] == GEOMETRY["coordinates"][0] and coords[-1] == GEOMETRY["coordinates"][-1]
    assert len(coords) < len(GEOMETRY["coordinates"])
    # Fuel stops come from the full geometry either way.
    assert light["fuel_plan"] == full["fuel_plan"]
    assert light["route"]["distance_miles"] == full["route"]["distance_miles"]


def test_invalid_geometry_detail(client: APIClient, osrm: FakeOsrm) -> None:
    response = post(client, geometry_detail="tiny")

    assert response.status_code == 400
    assert set(response.json()["error"]["details"]) == {"geometry_detail"}


def test_simplify_respects_tolerance() -> None:
    rng = random.Random(5)
    lon, lat, heading, coords = -100.0, 35.0, 0.0, []
    for _ in range(3000):  # winding road, ~70 m steps
        heading += rng.gauss(0, 0.08)
        lon += 0.0008 * math.cos(heading)
        lat += 0.0006 * math.sin(heading)
        coords.append([lon, lat])
    tolerance_m = 25.0
    kept = simplify(coords, tolerance_m)
    assert kept[0] == coords[0] and kept[-1] == coords[-1]
    assert len(kept) < len(coords) / 3

    kx = MILES_PER_DEGREE * math.cos(math.radians(35.5))
    segments = list(zip(kept, kept[1:], strict=False))

    def distance_m(p: list[float]) -> float:
        best = math.inf
        for (x1, y1), (x2, y2) in segments:
            ax, ay = (p[0] - x1) * kx, (p[1] - y1) * MILES_PER_DEGREE
            dx, dy = (x2 - x1) * kx, (y2 - y1) * MILES_PER_DEGREE
            ll = dx * dx + dy * dy
            t = 0 if ll == 0 else min(1, max(0, (ax * dx + ay * dy) / ll))
            best = min(best, math.hypot(ax - t * dx, ay - t * dy))
        return best * METERS_PER_MILE

    assert max(distance_m(p) for p in coords) <= tolerance_m * 1.01  # projection rounding


# --- caching, coalescing and reuse ---------------------------------------------------------


def test_cache_stores_geometry_as_text_and_reads_old_entries(
    osrm: FakeOsrm, monkeypatch: pytest.MonkeyPatch
) -> None:
    start, finish = CoordinateQuery(**START), CoordinateQuery(**FINISH)
    plan = services.plan_route(start, finish)
    key = services.route_cache_key(osrm.provider(), plan.origin, plan.destination)

    stored = cache.get(key)
    assert set(stored) == {"distance_meters", "duration_seconds", "geometry_json", "provider"}
    assert json.loads(stored["geometry_json"]) == GEOMETRY

    # An entry written by M2/M3 (parsed geometry) is still served.
    cache.set(key, {"distance_meters": 1.0, "duration_seconds": 2.0, "geometry": GEOMETRY,
                    "provider": "osrm"})  # fmt: skip
    again = services.plan_route(start, finish)
    assert again.cached and again.route.geometry == GEOMETRY and len(osrm.requests) == 1


class SlowOsrm(FakeOsrm):
    """Answers like ``FakeOsrm`` after a delay; optionally times out on the first request."""

    def __init__(self, delay: float, fail_first: bool = False) -> None:
        super().__init__()
        self.delay, self.fail_first = delay, fail_first
        self.lock = threading.Lock()

    def handler(self, request: httpx.Request) -> httpx.Response:
        with self.lock:
            first = not self.requests
        time.sleep(self.delay)
        if first and self.fail_first:
            with self.lock:
                self.requests.append(request)
            raise httpx.ReadTimeout("slow")
        with self.lock:
            return super().handler(request)


def _run_concurrently(count: int, provider: OsrmProvider) -> list[Any]:
    results: list[Any] = [None] * count
    barrier = threading.Barrier(count)

    def worker(index: int) -> None:
        barrier.wait()
        try:
            results[index] = services.plan_route(
                CoordinateQuery(**START), CoordinateQuery(**FINISH), provider=provider
            )
        except Exception as exc:  # noqa: BLE001 — collected for assertions
            results[index] = exc

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    return results


def test_concurrent_identical_requests_make_one_provider_call() -> None:
    slow = SlowOsrm(delay=0.4)

    results = _run_concurrently(6, slow.provider())

    assert len(slow.requests) == 1
    assert all(r.route.distance_miles == pytest.approx(700.0) for r in results)
    assert sorted(r.routing_requests for r in results) == [0, 0, 0, 0, 0, 1]


def test_waiting_request_takes_over_when_the_first_fails() -> None:
    slow = SlowOsrm(delay=0.2, fail_first=True)

    results = _run_concurrently(3, slow.provider())

    errors = [r for r in results if isinstance(r, Exception)]
    assert len(errors) == 1  # only the request whose provider call failed
    assert len(slow.requests) == 2  # one retry by a waiter, not one per waiter
    origin = services.resolve_location(CoordinateQuery(**START))
    destination = services.resolve_location(CoordinateQuery(**FINISH))
    lock_key = services.route_cache_key(slow.provider(), origin, destination) + ":lock"
    assert cache.get(lock_key) is None  # released after both the failure and the success


def test_database_cache_errors_still_return_a_plan(
    client: APIClient, osrm: FakeOsrm, stations: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*args: object, **kwargs: object) -> None:
        raise DatabaseError("no such table: routefuel_cache")

    for name in ("get", "set", "add", "delete"):
        monkeypatch.setattr(cache, name, broken)

    response = post(client)

    assert response.status_code == 200
    assert response.json()["meta"]["cached"] is False


def test_station_changes_are_picked_up_without_restart(
    client: APIClient, osrm: FakeOsrm, stations: None
) -> None:
    first = post(client).json()["fuel_plan"]["stops"]
    station = FuelStation.objects.get(opis_id=2)
    station.retail_price = station.max_retail_price = Decimal("2.90")
    station.save()

    second = post(client).json()["fuel_plan"]["stops"]

    assert first[0]["price_per_gallon"] == "3.100"
    assert second[0]["price_per_gallon"] == "2.900"
    assert len(osrm.requests) == 1  # route still cached


# --- errors, CORS --------------------------------------------------------------------------


def test_unexpected_errors_use_the_envelope_without_internals(
    client: APIClient, osrm: FakeOsrm, stations: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("secret internal detail /etc/passwd")

    monkeypatch.setattr(fuel_plans, "optimize", boom)

    response = post(client)

    assert response.status_code == 500
    assert response["Content-Type"] == "application/json"
    assert response.json() == {
        "error": {
            "code": "internal_error",
            "message": "An unexpected error occurred. Please try again later.",
            "details": None,
        }
    }
    assert b"secret" not in response.content and b"Traceback" not in response.content


@pytest.mark.parametrize(
    ("origin", "allowed"),
    [("http://localhost:3000", True), ("http://evil.example", False)],
)
def test_cors_preflight(client: APIClient, origin: str, allowed: bool) -> None:
    response = client.options(
        URL,
        HTTP_ORIGIN=origin,
        HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST",
        HTTP_ACCESS_CONTROL_REQUEST_HEADERS="content-type",
    )

    assert response.status_code == 200
    assert (response.get("Access-Control-Allow-Origin") == origin) is allowed


def test_cors_default_includes_both_local_dev_origins(monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib

    import config.settings as base

    monkeypatch.delenv("DJANGO_CORS_ALLOWED_ORIGINS", raising=False)
    monkeypatch.setattr("dotenv.load_dotenv", lambda *args, **kwargs: None)  # ignore local .env
    reloaded = importlib.reload(base)
    try:
        assert reloaded.CORS_ALLOWED_ORIGINS == ["http://localhost:3000", "http://127.0.0.1:3000"]
    finally:
        monkeypatch.undo()
        importlib.reload(base)


# --- renderer ------------------------------------------------------------------------------


def test_raw_json_renderer_splices_fragments() -> None:
    renderer = RawJSONRenderer()
    data = {"a": RawJSON('{"x":[1,2.5]}'), "b": "__rawjson_fake_0", "c": [" ", RawJSON("[]")]}

    output = renderer.render(data)

    assert json.loads(output) == {"a": {"x": [1, 2.5]}, "b": "__rawjson_fake_0", "c": [" ", []]}
    assert b"\xe2\x80\xa8" not in output  # U+2028 escaped for JavaScript


def test_route_geometry_forms_round_trip() -> None:
    parsed = Route(1.0, 1.0, GEOMETRY, "osrm")
    text = Route(1.0, 1.0, provider="osrm", geometry_json=parsed.geometry_json)

    assert text.geometry == GEOMETRY
    assert " " not in parsed.geometry_json
    with pytest.raises(ValueError):
        Route(1.0, 1.0, provider="osrm")


# --- performance regression and commands -----------------------------------------------------


@pytest.mark.django_db
def test_long_route_stays_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    """2,800-mile, 40k-point stand-in route with 400 stations along it.

    Generous bounds (5-10x the measured values) so the test only catches regressions such as
    accidental per-point queries or quadratic matching, not machine noise.
    """
    lat, west, east = 35.2, -117.0, -78.0  # stays inside the US along ~35.2 N
    points = 40_000
    coords = [[west + (east - west) * i / (points - 1), lat] for i in range(points)]
    miles = (east - west) * MILES_PER_DEGREE * math.cos(math.radians(lat))
    rng = random.Random(2)
    for i in range(400):
        FuelStation.objects.create(
            opis_id=10_000 + i, name=f"S{i}", address="", city="T", state="OK", rack_id=1,
            retail_price=D(rng.choice(["2.99", "3.09", "3.19", "3.29"])),
            max_retail_price=D("3.29"), latitude=lat + rng.uniform(-0.05, 0.05),
            longitude=west + (east - west) * (i + 0.5) / 400,
            geolocation_source="census_gazetteer_places_2010", geolocation_accuracy="city",
            location_uncertainty_miles=1.0,
        )  # fmt: skip

    requests: list[httpx.Request] = []
    geometry = {"type": "LineString", "coordinates": coords}
    body = {"code": "Ok", "routes": [{"distance": miles * 1.02 * METERS_PER_MILE,
            "duration": 1.0, "geometry": geometry}]}  # fmt: skip

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=body)

    provider = OsrmProvider("https://t.test", timeout=5, user_agent="t",
                            transport=httpx.MockTransport(handler))  # fmt: skip
    monkeypatch.setattr(services, "get_routing_provider", lambda: provider)
    api = APIClient()
    payload = {"start": {"latitude": lat, "longitude": west}, "finish": {"latitude": lat,
               "longitude": east}}  # fmt: skip

    started = time.perf_counter()
    first = api.post(URL, payload, format="json")
    uncached = time.perf_counter() - started
    started = time.perf_counter()
    second = api.post(URL, payload, format="json")
    cached = time.perf_counter() - started

    assert first.status_code == second.status_code == 200
    assert len(requests) == 1
    assert first.json()["fuel_plan"]["candidates"]["stations_on_route"] == 400
    assert len(second.json()["route"]["geometry"]["coordinates"]) == points
    assert second.json()["meta"]["timings_ms"]["optimization"] < 50
    assert uncached < 2.0 and cached < 1.0


@pytest.mark.django_db
def test_benchmark_command_runs(capsys: pytest.CaptureFixture[str]) -> None:
    call_command("benchmark_api", runs=1, route=["dallas-atlanta"], spacing=1.0)

    out = capsys.readouterr().out
    assert "STAND-IN provider (no network)" in out
    # The test database has no stations, so the plan is infeasible and reported as such.
    assert "dallas-atlanta: HTTP 422" in out


def test_settings_have_safe_routing_defaults() -> None:
    assert settings.ROUTING_BASE_URL.startswith("https://")
    assert settings.ROUTING_TIMEOUT > 0
