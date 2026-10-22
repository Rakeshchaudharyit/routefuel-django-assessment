"""Independent milligallon-grid checks: a coverage gap beyond the existing tenth-gallon DP."""

import random
from decimal import Decimal

import pytest

from apps.optimization.optimizer import Candidate, InfeasiblePlan, Vehicle, check_plan, optimize
from tests.reference_optimizer import reference_min_cost


@pytest.mark.parametrize("seed", [701, 702, 703])
def test_thousandth_gallon_instances_match_independent_dp(seed: int) -> None:
    rng = random.Random(seed)
    for _ in range(100):
        capacity = rng.randint(2, 10)
        initial = rng.randint(0, capacity)
        distance = rng.randint(1, 5 * capacity)
        stations = [
            (
                rng.randint(0, distance),
                rng.choice(
                    [Decimal("2.77566666"), Decimal("3.000"), Decimal("3.000"), Decimal("3.199")]
                ),
            )
            for _ in range(rng.randint(0, 10))
        ]
        expected = reference_min_cost(
            distance, [(m, p / 1000) for m, p in stations], capacity, 1, initial
        )
        candidates = [Candidate(i, mile / 1000, price) for i, (mile, price) in enumerate(stations)]
        vehicle = Vehicle(capacity / 1000, 1, initial / 1000)
        try:
            result = optimize(distance / 1000, candidates, vehicle)
        except InfeasiblePlan:
            assert expected is None
            continue
        assert expected is not None
        assert abs(result.exact_cost - expected) < Decimal("1e-10")
        assert all(p.gallons > 0 and p.fuel_on_arrival_gallons >= 0 for p in result.purchases)
        check_plan(result)


@pytest.mark.parametrize("delta", [-0.00001, 0, 0.00001])
def test_range_boundary_does_not_create_material_negative_fuel(delta: float) -> None:
    vehicle = Vehicle(500, 10, 50)
    if delta > 0:
        with pytest.raises(InfeasiblePlan):
            optimize(500 + delta, [], vehicle)
    else:
        result = optimize(500 + delta, [], vehicle)
        assert result.fuel_remaining_gallons >= 0
        assert not result.purchases
        check_plan(result)


def test_equal_exact_costs_can_have_negative_rounded_policy_delta() -> None:
    from apps.optimization.optimizer import reduce_stops
    from apps.routing.fuel_plans import _purchase_total

    candidates = [
        Candidate(1, 35.753825652495635, Decimal("3.00001")),
        Candidate(2, 343.40958641321083, Decimal("3.00001")),
    ]
    result = reduce_stops(760.0445386835747, candidates, Vehicle(500, 10, 50), Decimal("0.10"))
    assert len(result.minimum_cost_plan.purchases) == 2
    assert len(result.plan.purchases) == 1
    assert abs(result.plan.exact_cost - result.minimum_cost_plan.exact_cost) < Decimal("1e-10")
    assert _purchase_total(result.minimum_cost_plan) == Decimal("78.02")
    assert _purchase_total(result.plan) == Decimal("78.01")
    check_plan(result.plan)
