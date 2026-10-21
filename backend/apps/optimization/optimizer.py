"""Minimum-cost refuelling along a fixed route. Pure Python: no database, no network.

Model
-----
The vehicle drives a fixed route of ``distance_miles``, burning ``1 / mpg`` gallons per mile.
Fuel can be bought in any quantity at any candidate station (position ``mile`` along the
route, price per gallon ``price``) as long as the tank never holds more than
``tank_capacity_gallons``. The vehicle starts with ``starting_fuel_gallons``, which is already
paid for. The objective is to minimise money spent at stations; fuel left at the destination
is reported but has no value in the objective.

Algorithm ("fill up, refund later", O(n) after sorting)
--------------------------------------------------------
Drive forward through the stations in route order, keeping the tank as a queue of fuel
*lots* (price, gallons) in the order they were added:

* Driving consumes the oldest lot first.
* At a station with price ``p``, every lot still in the tank that was bought for more than
  ``p`` is handed back (it is treated as never bought), then the tank is topped up to
  capacity with fuel at ``p``.
* At the destination, all unconsumed purchased fuel is handed back.

What a station actually sells is the part of its lot that was consumed. Because refunds always
remove the most expensive fuel, lots in the tank are ordered by price (oldest = cheapest), so
every mile is driven on the cheapest fuel that could have been carried to that point within
the tank limit. This is the classical optimal strategy for the fixed-route, single-capacity
refuelling problem; ``tests/test_optimizer.py`` checks it against an independent
dynamic-programming solver on thousands of random instances.

Because the tank is notionally full on leaving every station, a plan exists if and only if
the starting fuel reaches the first station (or the destination) and no gap between
consecutive stations, or between the last station and the destination, exceeds the range.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from decimal import Decimal

EPSILON_GALLONS = 1e-9


@dataclass(frozen=True)
class Vehicle:
    range_miles: float
    mpg: float
    starting_fuel_gallons: float

    def __post_init__(self) -> None:
        if self.range_miles <= 0 or self.mpg <= 0:
            raise ValueError("range_miles and mpg must be positive.")
        if not 0 <= self.starting_fuel_gallons <= self.tank_capacity_gallons + EPSILON_GALLONS:
            raise ValueError("starting_fuel_gallons must be between 0 and the tank capacity.")

    @property
    def tank_capacity_gallons(self) -> float:
        return self.range_miles / self.mpg


@dataclass(frozen=True)
class Candidate:
    key: object  # caller's identifier, returned unchanged in the plan
    mile: float
    price: Decimal


@dataclass(frozen=True)
class Purchase:
    candidate: Candidate
    gallons: float
    fuel_on_arrival_gallons: float

    @property
    def fuel_on_departure_gallons(self) -> float:
        return self.fuel_on_arrival_gallons + self.gallons


@dataclass(frozen=True)
class FuelPlan:
    distance_miles: float
    vehicle: Vehicle
    purchases: tuple[Purchase, ...]
    gallons_consumed: float
    starting_fuel_used_gallons: float
    fuel_remaining_gallons: float

    @property
    def gallons_purchased(self) -> float:
        return sum(p.gallons for p in self.purchases)

    @property
    def exact_cost(self) -> Decimal:
        """Unrounded cost; the API rounds per stop (see ``apps.routing.fuel_plans``)."""
        return sum(
            (p.candidate.price * Decimal(repr(p.gallons)) for p in self.purchases), Decimal(0)
        )


class InfeasiblePlan(Exception):
    """No refuelling plan can complete the route."""

    def __init__(self, message: str, *, from_mile: float, to_mile: float, reach_miles: float):
        super().__init__(message)
        self.message = message
        self.from_mile = from_mile
        self.to_mile = to_mile
        self.reach_miles = reach_miles


@dataclass
class _Lot:
    candidate_index: int | None  # None = fuel already in the tank at the start
    price: Decimal | None
    gallons: float


def sort_candidates(candidates: list[Candidate]) -> list[Candidate]:
    """Route order; at the same mile, cheaper first (identical outcome, fewer refunds)."""
    return sorted(candidates, key=lambda c: (c.mile, c.price, str(c.key)))


def optimize(distance_miles: float, candidates: list[Candidate], vehicle: Vehicle) -> FuelPlan:
    if distance_miles < 0:
        raise ValueError("distance_miles must not be negative.")
    stations = sort_candidates([c for c in candidates if 0 <= c.mile <= distance_miles])
    capacity = vehicle.tank_capacity_gallons
    mpg = vehicle.mpg

    tank: deque[_Lot] = deque()
    if vehicle.starting_fuel_gallons > 0:
        tank.append(_Lot(None, None, vehicle.starting_fuel_gallons))
    consumed_from: dict[int | None, float] = {}
    position = 0.0
    previous_was_station = False

    for index, mile in [(i, s.mile) for i, s in enumerate(stations)] + [(-1, distance_miles)]:
        need = (mile - position) / mpg
        available = sum(lot.gallons for lot in tank)
        if available + EPSILON_GALLONS < need:
            reach = (
                vehicle.range_miles if previous_was_station else vehicle.starting_fuel_gallons * mpg
            )
            target = "the destination" if index == -1 else "the next fuel station"
            start = f"mile {position:.1f}" if previous_was_station else "the origin"
            raise InfeasiblePlan(
                f"No feasible fuel plan: {target} is {mile - position:.1f} miles from {start}, "
                f"but the vehicle can cover at most {reach:.1f} miles there.",
                from_mile=position,
                to_mile=mile,
                reach_miles=reach,
            )
        _consume(tank, need, consumed_from)
        position = mile
        if index == -1:
            break

        price = stations[index].price
        while tank and tank[-1].price is not None and tank[-1].price > price:
            tank.pop()  # refund fuel that was dearer than what is on sale here
        top_up = capacity - sum(lot.gallons for lot in tank)
        if top_up > EPSILON_GALLONS:
            tank.append(_Lot(index, price, top_up))
        previous_was_station = True

    return _build_plan(distance_miles, stations, vehicle, consumed_from)


def _consume(tank: deque[_Lot], gallons: float, consumed_from: dict[int | None, float]) -> None:
    remaining = gallons
    while remaining > EPSILON_GALLONS and tank:
        lot = tank[0]
        used = min(lot.gallons, remaining)
        consumed_from[lot.candidate_index] = consumed_from.get(lot.candidate_index, 0.0) + used
        lot.gallons -= used
        remaining -= used
        if lot.gallons <= EPSILON_GALLONS:
            tank.popleft()


def _build_plan(
    distance_miles: float,
    stations: list[Candidate],
    vehicle: Vehicle,
    consumed_from: dict[int | None, float],
) -> FuelPlan:
    purchases = []
    fuel = vehicle.starting_fuel_gallons
    position = 0.0
    for index, station in enumerate(stations):
        gallons = consumed_from.get(index, 0.0)
        if gallons <= EPSILON_GALLONS:
            continue
        fuel -= (station.mile - position) / vehicle.mpg
        purchases.append(Purchase(station, gallons, max(fuel, 0.0)))
        fuel += gallons
        position = station.mile

    consumed = distance_miles / vehicle.mpg
    start_used = min(vehicle.starting_fuel_gallons, consumed)
    plan = FuelPlan(
        distance_miles=distance_miles,
        vehicle=vehicle,
        purchases=tuple(purchases),
        gallons_consumed=consumed,
        starting_fuel_used_gallons=start_used,
        fuel_remaining_gallons=vehicle.starting_fuel_gallons - start_used,
    )
    check_plan(plan)
    return plan


class PlanCheckError(AssertionError):
    """An internal invariant failed. Never shown to users as a valid plan."""


def check_plan(plan: FuelPlan, tolerance: float = 1e-6) -> None:
    """Replay ``plan`` from the origin and verify every physical constraint."""
    vehicle = plan.vehicle
    capacity = vehicle.tank_capacity_gallons
    fuel = vehicle.starting_fuel_gallons
    position = 0.0
    for purchase in plan.purchases:
        mile = purchase.candidate.mile
        if mile < position - tolerance or mile > plan.distance_miles + tolerance:
            raise PlanCheckError(f"Stop at mile {mile} is out of route order.")
        if purchase.gallons <= 0:
            raise PlanCheckError("Purchases must be positive.")
        fuel -= (mile - position) / vehicle.mpg
        if fuel < -tolerance:
            raise PlanCheckError(f"Tank runs dry before mile {mile}.")
        fuel += purchase.gallons
        if fuel > capacity + tolerance:
            raise PlanCheckError(f"Tank over capacity at mile {mile}.")
        position = mile
    fuel -= (plan.distance_miles - position) / vehicle.mpg
    if fuel < -tolerance:
        raise PlanCheckError("Tank runs dry before the destination.")
    if abs(fuel - plan.fuel_remaining_gallons) > tolerance:
        raise PlanCheckError("Remaining fuel does not balance.")
    balance = plan.starting_fuel_used_gallons + plan.gallons_purchased - plan.gallons_consumed
    if abs(balance) > tolerance * (len(plan.purchases) + 1):
        raise PlanCheckError("Fuel bought plus starting fuel used must equal fuel consumed.")


@dataclass(frozen=True)
class StopReduction:
    plan: FuelPlan
    minimum_cost_plan: FuelPlan
    removed_keys: tuple[object, ...]


def reduce_stops(
    distance_miles: float,
    candidates: list[Candidate],
    vehicle: Vehicle,
    min_savings_per_stop: Decimal,
) -> StopReduction:
    """Optional practical-stop policy, separate from the minimum-cost optimiser.

    Start from the minimum-cost plan. Repeatedly try removing each used station (excluding it
    and re-optimising); take the removal that raises the purchase cost least, but only if the
    new plan has fewer stops and costs less than ``min_savings_per_stop`` more than the current
    plan. Stop when no removal qualifies.

    Guarantees: every returned plan is feasible and passes ``check_plan``; each removed stop
    saved less than the threshold; stop count strictly decreases each round. It is a greedy
    heuristic, not an exact minimiser of "fuel cost + cost per stop".
    """
    if min_savings_per_stop <= 0:
        raise ValueError("min_savings_per_stop must be positive.")
    best = optimize(distance_miles, candidates, vehicle)
    current, excluded = best, set()
    while current.purchases:
        options = []
        for purchase in current.purchases:
            trial_excluded = excluded | {purchase.candidate.key}
            remaining = [c for c in candidates if c.key not in trial_excluded]
            try:
                trial = optimize(distance_miles, remaining, vehicle)
            except InfeasiblePlan:
                continue
            extra = trial.exact_cost - current.exact_cost
            if len(trial.purchases) < len(current.purchases) and extra < min_savings_per_stop:
                options.append((extra, str(purchase.candidate.key), purchase.candidate.key, trial))
        if not options:
            break
        _, _, key, current = min(options, key=lambda option: (option[0], option[1]))
        excluded.add(key)
    removed = tuple(
        p.candidate.key
        for p in best.purchases
        if p.candidate.key not in {q.candidate.key for q in current.purchases}
    )
    return StopReduction(plan=current, minimum_cost_plan=best, removed_keys=removed)
