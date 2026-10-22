"""Reproduce M7 live QA against the configured provider and local station database.
Run from the repository root: .venv/bin/python docs/qa/m7_audit.py
Prints JSON evidence; clears only the route entries for the four audited journeys.
No test fixtures or replacement route geometry are used. Public calls are >=1.1s apart.
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django

django.setup()
from apps.fuel.models import FuelStation
from apps.optimization.optimizer import (
    Candidate,
    InfeasiblePlan,
    Vehicle,
    check_plan,
    optimize,
)
from apps.routing.fuel_plans import (
    clear_memos,
    display_geometry_json,
    fuel_plan_payload,
    plan_route_with_fuel,
)
from apps.routing.locations import (
    PlaceQuery,
    resolve_location,
)
from apps.routing.providers import get_routing_provider
from apps.routing.services import route_cache_key
from django.core.cache import cache
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext


class CountedProvider:
    def __init__(self):
        self.delegate = get_routing_provider()
        self.name = self.delegate.name
        self.base_url = self.delegate.base_url
        self.profile = self.delegate.profile
        self.calls = 0
        self.last = 0.0
        self.network_ms = []

    def route(self, start, finish):
        delay = 1.1 - (time.monotonic() - self.last)
        if delay > 0:
            time.sleep(delay)
        self.last = time.monotonic()
        self.calls += 1
        begin = time.perf_counter()
        try:
            return self.delegate.route(start, finish)
        finally:
            self.network_ms.append(round((time.perf_counter() - begin) * 1000, 3))


provider = CountedProvider()
client = Client(SERVER_NAME="localhost")
output = {
    "verified_at": datetime.now(ZoneInfo("Asia/Kolkata")).isoformat(),
    "stations": FuelStation.objects.count(),
    "geolocated": FuelStation.objects.filter(latitude__isnull=False).count(),
    "routes": [],
    "errors": [],
}
queries = {
    "Dallas, TX": PlaceQuery("Dallas", "TX"),
    "Atlanta, GA": PlaceQuery("Atlanta", "GA"),
    "New York, NY": PlaceQuery("New York", "NY"),
    "Los Angeles, CA": PlaceQuery("Los Angeles", "CA"),
    "Austin, TX": PlaceQuery("Austin", "TX"),
}


def money_audit(p):
    f = p["fuel_plan"]
    s = f["summary"]
    assert sum((Decimal(x["cost"]) for x in f["stops"]), Decimal(0)) == Decimal(
        s["total_purchase_cost"]
    )
    assert sum((Decimal(x["gallons"]) for x in f["stops"]), Decimal(0)) == Decimal(
        s["total_gallons_purchased"]
    )
    assert all(
        (Decimal(x["price_per_gallon"]) * Decimal(x["gallons"])).quantize(
            Decimal(".01"), ROUND_HALF_UP
        )
        == Decimal(x["cost"])
        for x in f["stops"]
    )
    assert all(
        x["location"]["approximate"] and x["location"]["accuracy"] == "city"
        for x in f["stops"]
    )
    return str(
        Decimal(s["starting_fuel_used_gallons"])
        + Decimal(s["total_gallons_purchased"])
        - Decimal(s["total_gallons_consumed"])
    )


with patch("apps.routing.services.get_routing_provider", return_value=provider):
    output["health"] = {
        "status": (r := client.get("/api/v1/health/")).status_code,
        "body": r.json(),
    }
    for start, finish in [
        ("Dallas, TX", "Atlanta, GA"),
        ("New York, NY", "Los Angeles, CA"),
        ("Dallas, TX", "Austin, TX"),
    ]:
        key = route_cache_key(
            provider,
            resolve_location(queries[start]),
            resolve_location(queries[finish]),
        )
        cache.delete(key)
        clear_memos()
        for repeat in range(2):
            before = provider.calls
            began = time.perf_counter()
            with CaptureQueriesContext(connection) as captured:
                r = client.post(
                    "/api/v1/routes/optimize/",
                    {"start": start, "finish": finish, "geometry_detail": "simplified"},
                    content_type="application/json",
                )
            elapsed = (time.perf_counter() - began) * 1000
            p = r.json()
            if r.status_code != 200:
                raise RuntimeError(p)
            assert (
                p["meta"]["routing_requests"]
                == provider.calls - before
                == (0 if repeat else 1)
            )
            assert p["meta"]["cached"] == bool(repeat)
            assert (
                p["route"]["geometry"]["type"] == "LineString"
                and len(p["route"]["geometry"]["coordinates"]) >= 2
            )
            balance = money_audit(p)
            output["routes"].append(
                {
                    "start": start,
                    "finish": finish,
                    "repeat": repeat,
                    "status": r.status_code,
                    "elapsed_ms": round(elapsed, 3),
                    "provider_ms": provider.network_ms[-1] if not repeat else 0,
                    "geometry_points": len(p["route"]["geometry"]["coordinates"]),
                    "distance_miles": p["route"]["distance_miles"],
                    "duration_minutes": p["route"]["duration_minutes"],
                    "summary": p["fuel_plan"]["summary"],
                    "meta": p["meta"],
                    "queries": len(captured),
                    "display_balance_gallons": balance,
                }
            )
    cases = [
        (
            "invalid_location",
            {"start": "Atlantis, GA", "finish": "Atlanta, GA"},
            422,
            "location_not_found",
        ),
        (
            "infeasible",
            {
                "start": "Dallas, TX",
                "finish": "Atlanta, GA",
                "vehicle": {"range_miles": 10},
            },
            422,
            "no_feasible_fuel_plan",
        ),
        (
            "unreachable",
            {
                "start": "Los Angeles, CA",
                "finish": {"latitude": 21.3069, "longitude": -157.8583},
            },
            422,
            "route_not_found",
        ),
        (
            "invalid_vehicle",
            {"start": "Dallas, TX", "finish": "Atlanta, GA", "vehicle": {"mpg": 0}},
            400,
            "invalid",
        ),
    ]
    for name, body, status, code in cases:
        before = provider.calls
        begin = time.perf_counter()
        r = client.post(
            "/api/v1/routes/optimize/", body, content_type="application/json"
        )
        p = r.json()
        assert r.status_code == status and p["error"]["code"] == code, (
            name,
            r.status_code,
            p,
        )
        output["errors"].append(
            {
                "case": name,
                "status": r.status_code,
                "code": p["error"]["code"],
                "elapsed_ms": round((time.perf_counter() - begin) * 1000, 3),
                "provider_calls": provider.calls - before,
            }
        )
    vehicle = Vehicle(500, 10, 50)
    result = plan_route_with_fuel(
        queries["New York, NY"], queries["Los Angeles, CA"], vehicle, provider=provider
    )
    check_plan(result.plan)
    candidates = [
        Candidate(k, v.mile, v.row["retail_price"]) for k, v in result.stations.items()
    ]
    # Independent minimum-stop DP: each vertex is a station, edges are full-tank-reachable legs.
    ordered = sorted(candidates, key=lambda c: (c.mile, str(c.key)))
    best = []
    parents = []
    for i, c in enumerate(ordered):
        options = (
            [(1, None)] if c.mile <= vehicle.starting_fuel_gallons * vehicle.mpg else []
        )
        options += [
            (best[j] + 1, j)
            for j in range(i)
            if best[j] is not None and c.mile - ordered[j].mile <= vehicle.range_miles
        ]
        choice = min(options, key=lambda x: x[0]) if options else (None, None)
        best.append(choice[0])
        parents.append(choice[1])
    exits = [
        (best[i], i)
        for i, c in enumerate(ordered)
        if best[i] is not None
        and result.plan.distance_miles - c.mile <= vehicle.range_miles
    ]
    count, index = min(exits)
    path = []
    while index is not None:
        path.append(
            {"opis_id": ordered[index].key, "mile": round(ordered[index].mile, 4)}
        )
        index = parents[index]
    output["minimum_stop_audit"] = {
        "minimum_stops": count,
        "candidate_count": len(candidates),
        "one_feasible_minimum_stop_path": list(reversed(path)),
    }
    output["policies"] = []
    for threshold in [None, "0.10", "1.00", "2.00", "5.00", "10.00"]:
        t = time.perf_counter()
        r = plan_route_with_fuel(
            queries["New York, NY"],
            queries["Los Angeles, CA"],
            vehicle,
            min_savings_per_stop=None if threshold is None else Decimal(threshold),
            provider=provider,
        )
        check_plan(r.plan)
        f = fuel_plan_payload(r)["fuel_plan"]
        output["policies"].append(
            {
                "threshold": threshold,
                "stops": len(r.plan.purchases),
                "purchase_cost": f["summary"]["total_purchase_cost"],
                "policy": f["stop_policy"],
                "elapsed_ms": round((time.perf_counter() - t) * 1000, 3),
            }
        )
    output["marginal_stops"] = []
    for purchase in result.plan.purchases:
        try:
            alternative = optimize(
                result.plan.distance_miles,
                [c for c in candidates if c.key != purchase.candidate.key],
                vehicle,
            )
        except InfeasiblePlan:
            continue
        output["marginal_stops"].append(
            {
                "opis_id": purchase.candidate.key,
                "gallons": round(purchase.gallons, 6),
                "cost_increase_if_excluded": str(
                    alternative.exact_cost - result.plan.exact_cost
                ),
                "alternative_stops": len(alternative.purchases),
            }
        )
    t = time.perf_counter()
    full_count = len(result.route_plan.route.geometry["coordinates"])
    geometry = display_geometry_json(result.route_plan.route, 25)
    output["geometry"] = {
        "full_points": full_count,
        "simplified_points": len(json.loads(geometry)["coordinates"]),
        "full_parse_and_warm_display_ms": round((time.perf_counter() - t) * 1000, 3),
    }
    output["provider_calls_total"] = provider.calls
print(json.dumps(output, indent=2))
