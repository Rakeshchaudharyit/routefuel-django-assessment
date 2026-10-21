"""Repeatable API benchmark.

    python manage.py benchmark_api                  # stand-in provider (offline), all routes
    python manage.py benchmark_api --runs 50 --route dallas-atlanta
    python manage.py benchmark_api --live --runs 5  # real configured provider (network)

Requests go through Django's test client (full middleware, view, serializer and renderer;
no socket). Only this benchmark's own route cache entries are deleted, never the whole cache.
Live mode makes one uncached provider call per route and waits >= 1.1 s between calls (the
public OSRM server allows 1 request per second).
"""

from __future__ import annotations

import json
import logging
import math
import statistics
import time
from collections.abc import Callable
from typing import Any
from unittest import mock

from django.core.cache import cache
from django.core.management.base import BaseCommand, CommandError
from django.test import Client, override_settings

from apps.optimization.geometry import RouteLine
from apps.optimization.optimizer import Candidate, Vehicle, optimize
from apps.routing import fuel_plans, services
from apps.routing.benchmarking import STAND_IN_ROUTES, StandInOsrm, stand_in_geometry
from apps.routing.locations import PlaceQuery, resolve_location
from apps.routing.providers import Coordinate, get_routing_provider
from apps.routing.views import fuel_plan_payload, route_plan_payload

ENDPOINT = "/api/v1/routes/optimize/"


def _summary(samples: list[float]) -> str:
    ordered = sorted(samples)
    text = f"median {statistics.median(ordered):7.1f} ms"
    if len(ordered) >= 20:
        p95 = ordered[min(len(ordered) - 1, math.ceil(0.95 * len(ordered)) - 1)]
        text += f" | p95 {p95:7.1f} ms"
    return text + f" | min {ordered[0]:6.1f} | max {ordered[-1]:6.1f} | n={len(ordered)}"


def _time(fn: Callable[[], Any], runs: int) -> tuple[list[float], Any]:
    samples, result = [], None
    for _ in range(runs):
        start = time.perf_counter()
        result = fn()
        samples.append((time.perf_counter() - start) * 1000)
    return samples, result


class Command(BaseCommand):
    help = "Benchmark POST /api/v1/routes/optimize/ stage by stage and end to end."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--route", choices=sorted(STAND_IN_ROUTES), action="append")
        parser.add_argument("--runs", type=int, default=20)
        parser.add_argument(
            "--spacing", type=float, default=0.06, help="stand-in point spacing, miles"
        )
        parser.add_argument("--live", action="store_true", help="use the configured real provider")

    def handle(self, *args: Any, **options: Any) -> None:
        runs = options["runs"]
        if runs < 1:
            raise CommandError("--runs must be >= 1")
        names = options["route"] or list(STAND_IN_ROUTES)
        logging.getLogger("httpx").setLevel(logging.WARNING)
        mode = "LIVE provider" if options["live"] else "STAND-IN provider (no network)"
        self.stdout.write(f"Mode: {mode}; runs per measurement: {runs}\n")
        with override_settings(ALLOWED_HOSTS=["testserver"]):
            for name in names:
                self._bench(name, runs, options["spacing"], options["live"])
                if options["live"]:
                    time.sleep(1.1)

    def _bench(self, name: str, runs: int, spacing: float, live: bool) -> None:
        route = STAND_IN_ROUTES[name]
        start_q = PlaceQuery(*[p.strip() for p in route.start.rsplit(",", 1)])
        finish_q = PlaceQuery(*[p.strip() for p in route.finish.rsplit(",", 1)])
        origin, destination = resolve_location(start_q), resolve_location(finish_q)

        if live:
            stand_in = None
            provider = get_routing_provider()
        else:
            coords, meters = stand_in_geometry(route, spacing)
            stand_in = StandInOsrm(coords, meters)
            provider = stand_in.provider()
        key = services.route_cache_key(provider, origin, destination)
        client = Client()
        body = json.dumps({"start": route.start, "finish": route.finish})
        out = self.stdout.write

        with mock.patch.object(services, "get_routing_provider", lambda: provider):
            cache.delete(key)
            # Uncached end to end (live: once only).
            uncached_runs = 1 if live else runs

            def uncached() -> Any:
                cache.delete(key)
                return client.post(ENDPOINT, body, content_type="application/json")

            uncached_ms, response = _time(uncached, uncached_runs)
            if response.status_code != 200:
                out(f"{name}: HTTP {response.status_code} {response.content[:300]!r}")
                return
            cached_ms, response = _time(
                lambda: client.post(ENDPOINT, body, content_type="application/json"), runs
            )
            payload = response.json()

            # Stage timings (cached route, warm process).
            route_plan = services.plan_route(start_q, finish_q, provider=provider)
            stages: dict[str, list[float]] = {}
            stages["location resolution (2 places)"], _ = _time(
                lambda: (resolve_location(start_q), resolve_location(finish_q)), runs
            )
            stages["route cache read"], _ = _time(lambda: services._cache_get(key), runs)
            if not live:
                stages["provider call (in-process, parse+validate)"], _ = _time(
                    lambda: provider.route(
                        Coordinate(origin.latitude, origin.longitude),
                        Coordinate(destination.latitude, destination.longitude),
                    ),
                    runs,
                )
            route_obj = route_plan.route
            coordinates = route_obj.geometry["coordinates"]
            stages["route geometry processing (cold)"], _ = _time(
                lambda: RouteLine(coordinates, route_obj.distance_miles), runs
            )
            stages["route geometry processing (reused)"], line = _time(
                lambda: fuel_plans.route_line(route_obj), runs
            )
            corridor = fuel_plans.corridor_miles()
            stages["station selection (cold: version + query + placement)"], _ = _time(
                lambda: fuel_plans._place_on_route(
                    line,
                    list(
                        fuel_plans._station_rows(
                            line, corridor, fuel_plans._station_data_version().max_uncertainty_miles
                        )
                    ),
                    corridor,
                ),
                runs,
            )
            stages["station selection (reused: version query only)"], placed = _time(
                lambda: fuel_plans.select_stations(route_obj, line, corridor), runs
            )
            on_route, _rows = placed
            candidates = [Candidate(k, s.mile, s.row["retail_price"]) for k, s in on_route.items()]
            vehicle = Vehicle(500, 10, 50)
            stages["fuel optimisation"], _ = _time(
                lambda: optimize(line.distance_miles, candidates, vehicle), runs
            )
            result = fuel_plans.plan_route_with_fuel(start_q, finish_q, vehicle, provider=provider)
            full = route_plan_payload(result.route_plan)
            full.update(fuel_plan_payload(result))
            renderer = fuel_plans.response_renderer()
            stages["JSON serialisation"], rendered = _time(lambda: renderer.render(full), runs)

        out(f"\n== {name} ({'live' if live else 'stand-in'}) ==")
        out(
            f"route: {payload['route']['distance_miles']} mi, "
            f"{len(payload['route']['geometry']['coordinates'])} geometry points, "
            f"response {len(response.content) / 1024:.0f} KiB"
        )
        cands = payload["fuel_plan"]["candidates"]
        out(
            f"stations: {cands['stations_in_search_area']} in search area -> "
            f"{cands['stations_on_route']} on route; stops "
            f"{payload['fuel_plan']['summary']['number_of_stops']}, purchase cost "
            f"${payload['fuel_plan']['summary']['total_purchase_cost']}"
        )
        out(f"end to end, uncached route:  {_summary(uncached_ms)}")
        out(f"end to end, cached route:    {_summary(cached_ms)}")
        for label, samples in stages.items():
            out(f"  {label:<56} {_summary(samples)}")
        out(f"  serialised size: {len(rendered) / 1024:.0f} KiB")
        if stand_in is not None:
            api_requests = stand_in.requests - runs  # minus the direct provider-stage calls
            out(
                f"provider requests from API calls: {api_requests} for {uncached_runs} uncached "
                f"and {runs} cached requests (expected {uncached_runs})"
            )
