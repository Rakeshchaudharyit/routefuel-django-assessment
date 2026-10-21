"""Route + fuel plan: the M2 route, M1 stations near it, and the M3 optimiser.

No routing calls are made per station: the single (cached) route from ``plan_route`` is reused
and every station is placed on it locally.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from functools import reduce
from typing import Any

from django.conf import settings
from django.db.models import Max, QuerySet

from apps.fuel.models import FuelStation, GeolocationAccuracy
from apps.fuel.queries import BoundingBox, routable_stations, stations_in_bounding_box
from apps.optimization.geometry import RouteLine
from apps.optimization.optimizer import Candidate, FuelPlan, Vehicle, optimize
from apps.routing.locations import LocationQuery
from apps.routing.providers import RoutingProvider
from apps.routing.services import RoutePlan, plan_route

GALLONS = Decimal("0.001")
CENTS = Decimal("0.01")
SEARCH_CHUNK_MILES = 200.0  # route split into pieces this long for the bounding-box prefilter

STATION_FIELDS = (
    "opis_id",
    "name",
    "address",
    "city",
    "state",
    "retail_price",
    "latitude",
    "longitude",
    "geolocation_source",
    "geolocation_accuracy",
    "location_uncertainty_miles",
)


@dataclass(frozen=True)
class OnRouteStation:
    row: dict[str, Any]
    mile: float
    offset_miles: float


@dataclass(frozen=True)
class FuelPlanResult:
    route_plan: RoutePlan
    vehicle: Vehicle
    starting_fuel_price: Decimal | None
    plan: FuelPlan
    stations: dict[int, OnRouteStation]  # by opis_id
    stations_in_search_area: int
    corridor_miles: float
    timings_ms: dict[str, float]


def plan_route_with_fuel(
    start: LocationQuery,
    finish: LocationQuery,
    vehicle: Vehicle,
    *,
    starting_fuel_price: Decimal | None = None,
    provider: RoutingProvider | None = None,
) -> FuelPlanResult:
    """Raises ``LocationError``, ``SameLocationError``, ``RoutingError`` or ``InfeasiblePlan``."""
    t0 = time.perf_counter()
    route_plan = plan_route(start, finish, provider=provider)
    t1 = time.perf_counter()
    line = RouteLine(route_plan.route.geometry["coordinates"], route_plan.route.distance_miles)
    corridor = settings.FUEL_CORRIDOR_MILES
    rows = list(_station_rows(line, corridor))
    on_route = _place_on_route(line, rows, corridor)
    t2 = time.perf_counter()
    candidates = [
        Candidate(opis_id, s.mile, s.row["retail_price"]) for opis_id, s in on_route.items()
    ]
    plan = optimize(line.distance_miles, candidates, vehicle)
    t3 = time.perf_counter()
    return FuelPlanResult(
        route_plan=route_plan,
        vehicle=vehicle,
        starting_fuel_price=starting_fuel_price,
        plan=plan,
        stations=on_route,
        stations_in_search_area=len(rows),
        corridor_miles=corridor,
        timings_ms={
            "route": round((t1 - t0) * 1000, 2),
            "station_matching": round((t2 - t1) * 1000, 2),
            "optimization": round((t3 - t2) * 1000, 2),
        },
    )


def _station_rows(line: RouteLine, corridor: float) -> QuerySet[FuelStation, dict[str, Any]]:
    """One indexed query: routable stations inside padded boxes around ~100-mile route pieces."""
    max_uncertainty = routable_stations().aggregate(m=Max("location_uncertainty_miles"))["m"] or 0.0
    padding = corridor + max_uncertainty
    boxes = []
    chunk: list[tuple[float, float]] = []
    chunk_start = 0.0
    for point, mile in zip(line.points, line.cumulative, strict=True):
        chunk.append(point)
        if mile - chunk_start >= SEARCH_CHUNK_MILES:
            boxes.append(BoundingBox.around(chunk, padding_miles=padding))
            chunk, chunk_start = [point], mile
    if len(chunk) > 1 or not boxes:
        boxes.append(BoundingBox.around(chunk, padding_miles=padding))
    querysets = [stations_in_bounding_box(box) for box in boxes]
    return reduce(lambda a, b: a | b, querysets).order_by().values(*STATION_FIELDS)


def _place_on_route(
    line: RouteLine, rows: list[dict[str, Any]], corridor: float
) -> dict[int, OnRouteStation]:
    """Stations whose point lies within ``corridor + uncertainty`` miles of the route."""
    placed: dict[int, OnRouteStation] = {}
    cache: dict[tuple[float, float, float], Any] = {}
    for row in rows:
        reach = corridor + (row["location_uncertainty_miles"] or 0.0)
        key = (row["latitude"], row["longitude"], reach)  # many stations share a town point
        if key not in cache:
            cache[key] = line.locate(row["latitude"], row["longitude"], reach)
        position = cache[key]
        if position is not None:
            placed[row["opis_id"]] = OnRouteStation(row, position.mile, position.offset_miles)
    return placed


# --- response ----------------------------------------------------------------------------


def _q(value: float | Decimal, step: Decimal) -> Decimal:
    return Decimal(repr(value) if isinstance(value, float) else value).quantize(
        step, rounding=ROUND_HALF_UP
    )


def _price(value: Decimal) -> str:
    """Source precision without trailing zeros, at least 3 decimals ("3.259", "3.00733333")."""
    text = format(value.normalize(), "f")
    whole, _, frac = text.partition(".")
    return f"{whole}.{frac.ljust(3, '0')}"


def fuel_plan_payload(result: FuelPlanResult) -> dict[str, Any]:
    plan, vehicle = result.plan, result.vehicle
    stops = []
    total_cost = Decimal("0.00")
    total_gallons = Decimal("0.000")
    for sequence, purchase in enumerate(plan.purchases, start=1):
        station = result.stations[purchase.candidate.key]
        row = station.row
        gallons = _q(purchase.gallons, GALLONS)
        cost = (row["retail_price"] * gallons).quantize(CENTS, rounding=ROUND_HALF_UP)
        total_cost += cost
        total_gallons += gallons
        approximate = row["geolocation_accuracy"] != GeolocationAccuracy.ADDRESS
        stops.append(
            {
                "sequence": sequence,
                "station": {
                    "opis_id": row["opis_id"],
                    "name": row["name"],
                    "address": row["address"],
                    "city": row["city"],
                    "state": row["state"],
                    "latitude": row["latitude"],
                    "longitude": row["longitude"],
                },
                "location": {
                    "accuracy": row["geolocation_accuracy"],
                    "source": row["geolocation_source"],
                    "approximate": approximate,
                    "uncertainty_miles": row["location_uncertainty_miles"],
                    "distance_from_route_miles": float(_q(station.offset_miles, CENTS)),
                },
                "route_mile": float(_q(purchase.candidate.mile, Decimal("0.1"))),
                "price_per_gallon": _price(row["retail_price"]),
                "gallons": str(gallons),
                "cost": str(cost),
                "fuel_on_arrival_gallons": str(_q(purchase.fuel_on_arrival_gallons, GALLONS)),
                "fuel_on_departure_gallons": str(_q(purchase.fuel_on_departure_gallons, GALLONS)),
            }
        )

    start_used = _q(plan.starting_fuel_used_gallons, GALLONS)
    start_value = None
    estimated_total = None
    if result.starting_fuel_price is not None:
        start_value = (result.starting_fuel_price * start_used).quantize(CENTS, ROUND_HALF_UP)
        estimated_total = total_cost + start_value

    return {
        "vehicle": {
            "range_miles": vehicle.range_miles,
            "mpg": vehicle.mpg,
            "tank_capacity_gallons": str(_q(vehicle.tank_capacity_gallons, GALLONS)),
            "starting_fuel_gallons": str(_q(vehicle.starting_fuel_gallons, GALLONS)),
            "starting_fuel_price_per_gallon": (
                None if result.starting_fuel_price is None else _price(result.starting_fuel_price)
            ),
        },
        "fuel_plan": {
            "currency": "USD",
            "stops": stops,
            "summary": {
                "number_of_stops": len(stops),
                "total_gallons_consumed": str(_q(plan.gallons_consumed, GALLONS)),
                "starting_fuel_used_gallons": str(start_used),
                "total_gallons_purchased": str(total_gallons),
                "total_purchase_cost": str(total_cost),
                "fuel_remaining_at_destination_gallons": str(
                    _q(plan.fuel_remaining_gallons, GALLONS)
                ),
                "starting_fuel_value": None if start_value is None else str(start_value),
                "estimated_total_fuel_cost": (
                    None if estimated_total is None else str(estimated_total)
                ),
            },
            "candidates": {
                "corridor_miles": result.corridor_miles,
                "stations_in_search_area": result.stations_in_search_area,
                "stations_on_route": len(result.stations),
            },
        },
    }
