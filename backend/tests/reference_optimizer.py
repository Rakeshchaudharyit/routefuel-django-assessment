"""Independent reference solver for small refuelling instances (tests only).

Dynamic programming over integer fuel levels: at each station try every whole-gallon purchase
that fits in the tank. Exact for instances where the starting fuel, tank capacity and every
leg's consumption are whole gallons: the problem is a linear program whose constraint matrix
is an interval (consecutive-ones) matrix, hence totally unimodular, so an optimal solution
with whole-gallon purchases exists.
"""

from __future__ import annotations

from decimal import Decimal

INFEASIBLE = None


def reference_min_cost(
    distance: int,
    stations: list[tuple[int, Decimal]],
    capacity: int,
    mpg: int,
    starting_fuel: int,
) -> Decimal | None:
    """Minimum purchase cost, or ``None`` if the destination cannot be reached."""
    events = sorted(s for s in stations if 0 <= s[0] <= distance)
    states: dict[int, Decimal] = {starting_fuel: Decimal(0)}
    position = 0
    for mile, price in [*events, (distance, None)]:
        assert (mile - position) % mpg == 0, "legs must consume whole gallons"
        burn = (mile - position) // mpg
        states = {fuel - burn: cost for fuel, cost in states.items() if fuel >= burn}
        if not states:
            return INFEASIBLE
        position = mile
        if price is None:
            break
        bought: dict[int, Decimal] = {}
        for fuel, cost in states.items():
            for extra in range(capacity - fuel + 1):
                total = cost + price * extra
                if fuel + extra not in bought or total < bought[fuel + extra]:
                    bought[fuel + extra] = total
        states = bought
    return min(states.values())
