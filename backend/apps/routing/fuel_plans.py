"""Route + fuel plan: the M2 route, M1 stations near it, and the M3 optimiser.

No routing calls are made per station: the single (cached) route from ``plan_route`` is reused
and every station is placed on it locally.
"""

from __future__ import annotations

import json
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from functools import reduce
from typing import Any

from django.conf import settings
from django.db.models import Count, Max, QuerySet

from apps.core.renderers import RawJSONRenderer
from apps.fuel.models import FuelStation, GeolocationAccuracy
from apps.fuel.queries import BoundingBox, routable_stations, stations_in_bounding_box
from apps.optimization.geometry import RouteLine, simplify
from apps.optimization.optimizer import (
    Candidate,
    FuelPlan,
    StopReduction,
    Vehicle,
    optimize,
    reduce_stops,
)
from apps.routing.locations import LocationQuery
from apps.routing.providers import Route, RoutingProvider
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
    min_savings_per_stop: Decimal | None
    reduction: StopReduction | None  # set only when the practical-stop policy was requested
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
    min_savings_per_stop: Decimal | None = None,
    provider: RoutingProvider | None = None,
) -> FuelPlanResult:
    """Raises ``LocationError``, ``SameLocationError``, ``RoutingError`` or ``InfeasiblePlan``."""
    t0 = time.perf_counter()
    route_plan = plan_route(start, finish, provider=provider)
    t1 = time.perf_counter()
    line = route_line(route_plan.route)
    corridor = corridor_miles()
    on_route, rows_in_area = select_stations(route_plan.route, line, corridor)
    t2 = time.perf_counter()
    candidates = [
        Candidate(opis_id, s.mile, s.row["retail_price"]) for opis_id, s in on_route.items()
    ]
    reduction = None
    if min_savings_per_stop is None:
        plan = optimize(line.distance_miles, candidates, vehicle)
    else:
        reduction = reduce_stops(line.distance_miles, candidates, vehicle, min_savings_per_stop)
        plan = reduction.plan
    t3 = time.perf_counter()
    return FuelPlanResult(
        route_plan=route_plan,
        vehicle=vehicle,
        starting_fuel_price=starting_fuel_price,
        plan=plan,
        min_savings_per_stop=min_savings_per_stop,
        reduction=reduction,
        stations=on_route,
        stations_in_search_area=rows_in_area,
        corridor_miles=corridor,
        timings_ms={
            "route": round((t1 - t0) * 1000, 2),
            "station_matching": round((t2 - t1) * 1000, 2),
            "optimization": round((t3 - t2) * 1000, 2),
        },
    )


def corridor_miles() -> float:
    return settings.FUEL_CORRIDOR_MILES


_ROUTE_LINES: OrderedDict[tuple[str, float], RouteLine] = OrderedDict()
_ROUTE_LINES_MAX = 32
_ROUTE_LINES_LOCK = threading.Lock()


def route_line(route: Route) -> RouteLine:
    """The route's ``RouteLine``, reused across requests for the same route in this process.

    Keyed by the geometry text itself, so a stale entry can never be returned for a changed
    route. Each entry holds only the thinned line (a few thousand vertices).
    """
    key = (route.geometry_json, route.distance_miles)
    with _ROUTE_LINES_LOCK:
        line = _ROUTE_LINES.get(key)
        if line is not None:
            _ROUTE_LINES.move_to_end(key)
            return line
    line = RouteLine(route.geometry["coordinates"], route.distance_miles)
    with _ROUTE_LINES_LOCK:
        _ROUTE_LINES[key] = line
        while len(_ROUTE_LINES) > _ROUTE_LINES_MAX:
            _ROUTE_LINES.popitem(last=False)
    return line


@dataclass(frozen=True)
class _StationDataVersion:
    count: int
    last_updated: object
    max_uncertainty_miles: float


def _station_data_version() -> _StationDataVersion:
    """One aggregate query. Changes whenever routable station data is imported or edited."""
    row = routable_stations().aggregate(
        count=Count("id"), updated=Max("updated_at"), uncertainty=Max("location_uncertainty_miles")
    )
    return _StationDataVersion(row["count"], row["updated"], row["uncertainty"] or 0.0)


_SELECTIONS: OrderedDict[tuple[Any, ...], tuple[dict[int, OnRouteStation], int]] = OrderedDict()
_SELECTIONS_MAX = 32
_SELECTIONS_LOCK = threading.Lock()


def select_stations(
    route: Route, line: RouteLine, corridor: float
) -> tuple[dict[int, OnRouteStation], int]:
    """Stations on the route (by OPIS ID) and how many rows the prefilter returned.

    Reused per process for the same route, corridor and station-data version; the version
    query runs on every call, so an import or edit is picked up on the next request.
    """
    version = _station_data_version()
    key = (route.geometry_json, route.distance_miles, corridor, version)
    with _SELECTIONS_LOCK:
        hit = _SELECTIONS.get(key)
        if hit is not None:
            _SELECTIONS.move_to_end(key)
            return hit
    rows = list(_station_rows(line, corridor, version.max_uncertainty_miles))
    result = (_place_on_route(line, rows, corridor), len(rows))
    with _SELECTIONS_LOCK:
        _SELECTIONS[key] = result
        while len(_SELECTIONS) > _SELECTIONS_MAX:
            _SELECTIONS.popitem(last=False)
    return result


DISPLAY_TOLERANCE_METERS = 25.0
_DISPLAY: OrderedDict[tuple[str, float], str] = OrderedDict()
_DISPLAY_MAX = 32


def display_geometry_json(route: Route, tolerance_meters: float) -> str:
    """Simplified LineString text for drawing the route (never used for mile markers).

    Douglas-Peucker: every dropped point is within ``tolerance_meters`` of the line kept.
    Computed once per route and tolerance in this process (~150 ms for 42k winding points).
    """
    key = (route.geometry_json, tolerance_meters)
    with _ROUTE_LINES_LOCK:
        hit = _DISPLAY.get(key)
        if hit is not None:
            _DISPLAY.move_to_end(key)
            return hit
    coordinates = simplify(route.geometry["coordinates"], tolerance_meters)
    text = json.dumps({"type": "LineString", "coordinates": coordinates}, separators=(",", ":"))
    with _ROUTE_LINES_LOCK:
        _DISPLAY[key] = text
        while len(_DISPLAY) > _DISPLAY_MAX:
            _DISPLAY.popitem(last=False)
    return text


def response_renderer() -> RawJSONRenderer:
    return RawJSONRenderer()


def _station_rows(
    line: RouteLine, corridor: float, max_uncertainty: float
) -> QuerySet[FuelStation, dict[str, Any]]:
    """One indexed query: routable stations inside padded boxes around ~200-mile route pieces."""
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


def _line_items(plan: FuelPlan) -> list[tuple[Decimal, Decimal]]:
    """(gallons, cost) per stop exactly as shown to the client: gallons to 0.001, then
    price x gallons rounded half-up to the cent."""
    items = []
    for purchase in plan.purchases:
        gallons = _q(purchase.gallons, GALLONS)
        items.append((gallons, (purchase.candidate.price * gallons).quantize(CENTS, ROUND_HALF_UP)))
    return items


def _purchase_total(plan: FuelPlan) -> Decimal:
    return sum((cost for _, cost in _line_items(plan)), Decimal("0.00"))


def fuel_plan_payload(result: FuelPlanResult) -> dict[str, Any]:
    plan, vehicle = result.plan, result.vehicle
    stops = []
    total_cost = Decimal("0.00")
    total_gallons = Decimal("0.000")
    items = _line_items(plan)
    for sequence, (purchase, (gallons, cost)) in enumerate(
        zip(plan.purchases, items, strict=True), 1
    ):
        station = result.stations[purchase.candidate.key]
        row = station.row
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
        cost_note = (
            f"Purchases (${total_cost}) plus {start_used} gal of starting fuel valued at "
            f"${_price(result.starting_fuel_price)}/gal."
        )
    elif start_used == 0:
        start_value = Decimal("0.00")
        estimated_total = total_cost
        cost_note = "No starting fuel was used, so every gallon burnt was bought on the route."
    else:
        cost_note = (
            f"Whole-trip fuel cost is unavailable: {start_used} gal of starting fuel were used "
            "and starting_fuel_price_per_gallon was not provided. total_purchase_cost covers "
            "only fuel bought at the recommended stops."
        )

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
                "estimated_total_fuel_cost_status": (
                    "unavailable" if estimated_total is None else "calculated"
                ),
                "cost_note": cost_note,
            },
            "stop_policy": _stop_policy_payload(result),
            "candidates": {
                "corridor_miles": result.corridor_miles,
                "stations_in_search_area": result.stations_in_search_area,
                "stations_on_route": len(result.stations),
            },
        },
    }


def _stop_policy_payload(result: FuelPlanResult) -> dict[str, Any] | None:
    if result.reduction is None:
        return None
    minimum = _purchase_total(result.reduction.minimum_cost_plan)
    chosen = _purchase_total(result.reduction.plan)
    return {
        "min_savings_per_stop": str(result.min_savings_per_stop),
        "stops_removed": len(result.reduction.removed_keys),
        "removed_station_opis_ids": list(result.reduction.removed_keys),
        "minimum_purchase_cost": str(minimum),
        "minimum_cost_number_of_stops": len(result.reduction.minimum_cost_plan.purchases),
        "extra_cost": str(chosen - minimum),
    }


def clear_memos() -> None:
    """Drop per-process route-line and station-selection reuse (tests and benchmarks)."""
    with _ROUTE_LINES_LOCK:
        _ROUTE_LINES.clear()
    with _SELECTIONS_LOCK:
        _SELECTIONS.clear()
    with _ROUTE_LINES_LOCK:
        _DISPLAY.clear()
