"""Fuel optimiser: hand-worked cases, edge cases, and a randomised check against a DP solver."""

from __future__ import annotations

import random
from decimal import Decimal

import pytest

from apps.optimization.optimizer import (
    Candidate,
    FuelPlan,
    InfeasiblePlan,
    PlanCheckError,
    Purchase,
    Vehicle,
    check_plan,
    optimize,
)
from tests.reference_optimizer import reference_min_cost

TRUCK = Vehicle(range_miles=500, mpg=10, starting_fuel_gallons=50)
EMPTY_TRUCK = Vehicle(range_miles=500, mpg=10, starting_fuel_gallons=0)
D = Decimal


def station(key: str, mile: float, price: str) -> Candidate:
    return Candidate(key, mile, D(price))


def bought(plan: FuelPlan) -> dict[object, float]:
    return {p.candidate.key: round(p.gallons, 9) for p in plan.purchases}


# --- vehicle model -------------------------------------------------------------------


def test_default_truck_has_50_gallon_tank() -> None:
    assert TRUCK.tank_capacity_gallons == 50


@pytest.mark.parametrize(
    ("range_miles", "mpg", "start"), [(0, 10, 0), (500, 0, 0), (500, 10, -1), (500, 10, 50.1)]
)
def test_invalid_vehicle(range_miles: float, mpg: float, start: float) -> None:
    with pytest.raises(ValueError):
        Vehicle(range_miles=range_miles, mpg=mpg, starting_fuel_gallons=start)


# --- route length vs range ---------------------------------------------------------------


def test_short_route_needs_no_fuel_with_full_tank() -> None:
    plan = optimize(300, [station("a", 100, "3.00")], TRUCK)

    assert plan.purchases == ()
    assert plan.gallons_consumed == 30
    assert plan.starting_fuel_used_gallons == 30
    assert plan.fuel_remaining_gallons == 20
    assert plan.exact_cost == 0


def test_exactly_500_miles_on_a_full_tank() -> None:
    plan = optimize(500, [], TRUCK)

    assert plan.purchases == ()
    assert plan.fuel_remaining_gallons == 0


def test_just_over_500_miles_without_stations_is_infeasible() -> None:
    with pytest.raises(InfeasiblePlan) as info:
        optimize(500.01, [], TRUCK)

    assert info.value.from_mile == 0
    assert info.value.to_mile == 500.01
    assert info.value.reach_miles == 500


def test_route_between_500_and_1000_miles_buys_only_the_shortfall() -> None:
    plan = optimize(800, [station("a", 300, "3.00")], TRUCK)

    assert bought(plan) == {"a": 30.0}  # 80 gal needed, 50 in the tank
    assert plan.exact_cost == D("90.00")
    assert plan.fuel_remaining_gallons == 0
    (purchase,) = plan.purchases
    assert purchase.fuel_on_arrival_gallons == 20
    assert purchase.fuel_on_departure_gallons == 50


def test_long_route_with_several_stops() -> None:
    stations = [station(str(m), m, "3.00") for m in (400, 800, 1200, 1600, 2000, 2400)]

    plan = optimize(2700, stations, TRUCK)

    assert plan.gallons_consumed == 270
    assert plan.gallons_purchased == pytest.approx(220)
    assert plan.exact_cost == D("660.00")
    assert len(plan.purchases) >= 4  # at least ceil(2200 / 500) refuels
    check_plan(plan)


# --- price awareness ---------------------------------------------------------------------


def test_buys_little_before_a_cheaper_station() -> None:
    # Empty start. Expensive at 0, cheap at 100: buy just enough to reach the cheap one.
    plan = optimize(600, [station("dear", 0, "4.00"), station("cheap", 100, "3.00")], EMPTY_TRUCK)

    assert bought(plan) == {"dear": 10.0, "cheap": 50.0}
    assert plan.exact_cost == D("190.00")


def test_fills_up_at_cheap_station_before_expensive_ones() -> None:
    plan = optimize(900, [station("cheap", 0, "3.00"), station("dear", 450, "4.00")], EMPTY_TRUCK)

    assert bought(plan) == {"cheap": 50.0, "dear": 40.0}
    assert plan.exact_cost == D("310.00")


def test_cheapest_next_station_is_not_globally_optimal() -> None:
    # A "go to the cheapest station in range and fill up" rule would fill 50 gal at B (3.20);
    # the optimum buys only enough at B to reach C, which is cheaper still.
    stations = [station("B", 100, "3.20"), station("A", 400, "3.50"), station("C", 450, "3.00")]
    start = Vehicle(500, 10, 10)

    plan = optimize(900, stations, start)

    assert bought(plan) == {"B": 35.0, "C": 45.0}
    assert plan.exact_cost == D("247.00")
    assert plan.exact_cost == reference_min_cost(
        900, [(100, D("3.20")), (400, D("3.50")), (450, D("3.00"))], 50, 10, 10
    )


def test_nearest_station_is_not_chosen_just_for_being_near() -> None:
    stations = [station("near", 10, "4.50"), station("far", 300, "3.00")]

    plan = optimize(700, stations, TRUCK)

    assert bought(plan) == {"far": 20.0}


@pytest.mark.parametrize("order", [["a", "b"], ["b", "a"]])
def test_equal_prices_cost_the_same_and_are_deterministic(order: list[str]) -> None:
    miles = {"a": 300, "b": 300}
    stations = [station(key, miles[key], "3.25") for key in order]

    plan = optimize(800, stations, TRUCK)

    assert plan.exact_cost == D("97.50")
    assert bought(plan) == {"a": 30.0}  # ties broken by key, not input order


def test_duplicate_stations_at_one_place_use_the_cheapest() -> None:
    stations = [station("x1", 250, "3.40"), station("x2", 250, "3.10"), station("x3", 250, "3.40")]

    plan = optimize(700, stations, TRUCK)

    assert bought(plan) == {"x2": 20.0}


def test_decimal_prices_keep_full_precision() -> None:
    plan = optimize(600, [station("a", 200, "3.00733333")], TRUCK)

    assert plan.exact_cost == D("3.00733333") * 10


# --- starting fuel -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("start", "expected"),
    # The tank limits how much cheap fuel fits at mile 50 (arrival fuel + purchase <= 50 gal).
    [
        (50, {"cheap": 5.0, "end": 5.0}),
        (25, {"cheap": 30.0, "end": 5.0}),
        (5, {"cheap": 50.0, "end": 5.0}),
    ],
)
def test_starting_fuel_variations(start: float, expected: dict[str, float]) -> None:
    stations = [station("cheap", 50, "3.00"), station("end", 500, "3.50")]

    plan = optimize(600, stations, Vehicle(500, 10, start))

    assert bought(plan) == expected
    assert plan.starting_fuel_used_gallons == start
    assert plan.starting_fuel_used_gallons + plan.gallons_purchased == pytest.approx(60)


def test_insufficient_starting_fuel_to_reach_first_station() -> None:
    with pytest.raises(InfeasiblePlan, match="from the origin") as info:
        optimize(400, [station("a", 120, "3.00")], Vehicle(500, 10, 10))

    assert info.value.reach_miles == 100


def test_empty_tank_with_station_at_origin() -> None:
    plan = optimize(200, [station("o", 0, "3.00")], EMPTY_TRUCK)

    assert bought(plan) == {"o": 20.0}
    assert plan.purchases[0].fuel_on_arrival_gallons == 0


def test_leftover_starting_fuel_is_reported_not_bought() -> None:
    plan = optimize(120, [station("a", 60, "2.50")], TRUCK)

    assert plan.purchases == ()
    assert plan.fuel_remaining_gallons == 38


# --- feasibility -----------------------------------------------------------------------


def test_gap_between_stations_longer_than_range() -> None:
    stations = [station("a", 400, "3.00"), station("b", 950, "3.00")]

    with pytest.raises(InfeasiblePlan, match="next fuel station is 550.0 miles from mile 400.0"):
        optimize(1200, stations, TRUCK)


def test_last_station_too_far_from_destination() -> None:
    with pytest.raises(InfeasiblePlan, match="destination is 501.0 miles"):
        optimize(901, [station("a", 400, "3.00")], TRUCK)


def test_station_close_to_destination() -> None:
    plan = optimize(520, [station("a", 499, "3.00")], TRUCK)

    assert bought(plan) == {"a": pytest.approx(2.0)}  # arrives with 0.1 gal, needs 2.1


def test_stations_outside_the_route_are_ignored() -> None:
    stations = [
        station("before", -5, "1.00"),
        station("after", 605, "1.00"),
        station("a", 300, "3.00"),
    ]

    plan = optimize(600, stations, TRUCK)

    assert bought(plan) == {"a": 10.0}


# --- plan checker ----------------------------------------------------------------------


def _plan(purchases: list[Purchase], *, distance: float = 600, start: float = 50) -> FuelPlan:
    vehicle = Vehicle(500, 10, start)
    total = sum(p.gallons for p in purchases)
    return FuelPlan(
        distance,
        vehicle,
        tuple(purchases),
        distance / 10,
        min(start, distance / 10),
        start + total - distance / 10,
    )


def test_check_plan_rejects_over_capacity() -> None:
    plan = _plan([Purchase(station("a", 10, "3"), 10, 49)])

    with pytest.raises(PlanCheckError, match="over capacity"):
        check_plan(plan)


def test_check_plan_rejects_running_dry() -> None:
    plan = _plan([Purchase(station("a", 550, "3"), 10, 0)], distance=560)

    with pytest.raises(PlanCheckError, match="runs dry"):
        check_plan(plan)


# --- independent verification ----------------------------------------------------------

PRICES = [D(p) for p in ("2.999", "3.105", "3.25", "3.25", "3.49", "3.00733333", "4.10")]


@pytest.mark.parametrize("seed", range(20))
def test_matches_dynamic_programming_reference(seed: int) -> None:
    """500 random instances per seed; every one must agree on feasibility and cost."""
    rng = random.Random(seed)
    feasible = 0
    for _ in range(500):
        mpg = rng.choice([1, 2, 5, 10])
        capacity = rng.randint(1, 10)
        start = rng.randint(0, capacity)
        distance = mpg * rng.randint(0, 6 * capacity)
        stations = [
            (mpg * rng.randint(0, distance // mpg), rng.choice(PRICES))
            for _ in range(rng.randint(0, 12))
        ]
        expected = reference_min_cost(distance, stations, capacity, mpg, start)
        candidates = [Candidate(i, float(m), p) for i, (m, p) in enumerate(stations)]
        try:
            plan = optimize(float(distance), candidates, Vehicle(capacity * mpg, mpg, start))
        except InfeasiblePlan:
            assert expected is None, (distance, stations, capacity, mpg, start)
            continue
        assert expected is not None, (distance, stations, capacity, mpg, start)
        assert abs(plan.exact_cost - expected) < D("1e-6"), (
            distance,
            stations,
            capacity,
            mpg,
            start,
        )
        check_plan(plan)
        feasible += 1
    assert feasible > 100  # the generator must exercise real plans, not just failures


@pytest.mark.parametrize("seed", range(5))
def test_matches_reference_with_fractional_gallons(seed: int) -> None:
    """Truck-like numbers (10 MPG, whole miles, so legs burn tenths of a gallon).

    The reference runs in tenth-of-a-gallon units: 1 unit = 1 mile, price per unit = price / 10.
    """
    rng = random.Random(1000 + seed)
    for _ in range(200):
        capacity = rng.randint(3, 12)  # gallons
        start_tenths = rng.randint(0, capacity * 10)
        distance = rng.randint(0, 40 * capacity)
        stations = [
            (rng.randint(0, distance), rng.choice(PRICES)) for _ in range(rng.randint(0, 10))
        ]
        expected = reference_min_cost(
            distance, [(m, p / 10) for m, p in stations], capacity * 10, 1, start_tenths
        )
        candidates = [Candidate(i, float(m), p) for i, (m, p) in enumerate(stations)]
        vehicle = Vehicle(capacity * 10, 10, start_tenths / 10)
        try:
            plan = optimize(float(distance), candidates, vehicle)
        except InfeasiblePlan:
            assert expected is None
            continue
        assert expected is not None
        assert abs(plan.exact_cost - expected) < D("1e-6")
