"""Live end-to-end check against the configured routing provider (needs network access).

    python manage.py verify_routing
    python manage.py verify_routing --start "Chicago, IL" --finish "Denver, CO"

Steps: show configuration and DNS → one direct provider call through the Django client →
POST /api/v1/routes/ uncached then cached → POST /api/v1/routes/optimize/ (served from the
route cache). At most two provider requests, 1.1 s apart (public OSRM allows 1 req/s).
Exit status 1 if any check fails. Nothing is mocked.
"""

from __future__ import annotations

import json
import os
import socket
import time
from typing import Any
from urllib.parse import urlsplit

from django.conf import settings
from django.core.cache import cache
from django.core.management.base import BaseCommand, CommandError
from django.test import Client, override_settings

from apps.routing import services
from apps.routing.locations import LocationError, PlaceQuery, resolve_location
from apps.routing.providers import Coordinate, RoutingError, get_routing_provider

# Driving distance the public OSRM server returned for the Census points of Dallas, TX and
# Atlanta, GA on 2026-10-21 (1,253,364 m). Used only as a plausibility check.
REFERENCE_MILES = {("Dallas, TX", "Atlanta, GA"): 778.8}


def _place(text: str) -> PlaceQuery:
    city, _, state = text.rpartition(",")
    if not city:
        raise CommandError(f'Use "City, ST": {text!r}')
    return PlaceQuery(city.strip(), state.strip())


class Command(BaseCommand):
    help = "Verify routing against the real provider through the Django client and API."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--start", default="Dallas, TX")
        parser.add_argument("--finish", default="Atlanta, GA")

    def handle(self, *args: Any, **options: Any) -> None:
        self.failures = 0
        start, finish = options["start"], options["finish"]
        url = urlsplit(settings.ROUTING_BASE_URL)
        self.stdout.write("Configuration")
        self.stdout.write(f"  ROUTING_BASE_URL   {settings.ROUTING_BASE_URL}")
        self.stdout.write(
            f"  scheme             {url.scheme} (TLS verification: httpx default, on)"
        )
        self.stdout.write(
            f"  ROUTING_TIMEOUT    {settings.ROUTING_TIMEOUT}s (connect capped at 5s)"
        )
        self.stdout.write(f"  ROUTING_USER_AGENT {settings.ROUTING_USER_AGENT}")
        proxies = sorted(
            k for k in os.environ if k.lower() in {"https_proxy", "http_proxy", "all_proxy"}
        )
        self.stdout.write(f"  proxy variables    {', '.join(proxies) or 'none'} (values not shown)")
        try:
            addresses = {info[4][0] for info in socket.getaddrinfo(url.hostname, 443)}
            self.stdout.write(f"  DNS {url.hostname}: {', '.join(sorted(addresses))}")
        except OSError as exc:
            self.stdout.write(
                f"  DNS {url.hostname}: not resolvable here ({exc}); a proxy may resolve it"
            )

        try:
            origin, destination = resolve_location(_place(start)), resolve_location(_place(finish))
        except LocationError as exc:
            raise CommandError(f"{exc.code}: {exc.message}") from exc

        self.stdout.write(f"\n1. Direct provider call: {origin.label} -> {destination.label}")
        provider = get_routing_provider()
        began = time.perf_counter()
        try:
            route = provider.route(
                Coordinate(origin.latitude, origin.longitude),
                Coordinate(destination.latitude, destination.longitude),
            )
        except RoutingError as exc:
            self._check(False, f"provider call failed: {exc.code} — {exc.message}")
            raise CommandError("Live routing is not reachable from this machine.") from exc
        elapsed = (time.perf_counter() - began) * 1000
        coords = route.geometry["coordinates"]
        self._check(True, f"HTTP OK in {elapsed:.0f} ms")
        self._check(route.distance_miles > 0, f"distance {route.distance_miles:.2f} mi")
        self._check(route.duration_minutes > 0, f"duration {route.duration_minutes:.1f} min")
        self._check(
            route.geometry["type"] == "LineString" and len(coords) >= 2,
            f"GeoJSON LineString with {len(coords)} points",
        )
        reference = REFERENCE_MILES.get((start, finish))
        if reference:
            self._check(
                abs(route.distance_miles - reference) / reference < 0.03,
                f"distance within 3% of the {reference} mi reference",
            )

        time.sleep(1.1)
        key = services.route_cache_key(provider, origin, destination)
        cache.delete(key)
        body = json.dumps({"start": start, "finish": finish})
        client = Client()
        with override_settings(ALLOWED_HOSTS=["testserver"]):
            self.stdout.write("\n2. POST /api/v1/routes/ (cache cleared for this pair)")
            began = time.perf_counter()
            first = client.post("/api/v1/routes/", body, content_type="application/json")
            first_ms = (time.perf_counter() - began) * 1000
            ok = first.status_code == 200
            self._check(ok, f"HTTP {first.status_code} in {first_ms:.0f} ms")
            if not ok:
                self.stdout.write(f"   {first.content[:400]!r}")
                raise CommandError("The routes endpoint failed against the live provider.")
            data = first.json()
            self._check(data["meta"]["routing_requests"] == 1, "routing_requests == 1 (uncached)")
            self._check(data["meta"]["provider"] == "osrm", f"provider {data['meta']['provider']}")
            route_data = data["route"]
            self.stdout.write(
                f"   {route_data['distance_miles']} mi, {route_data['duration_minutes']} min, "
                f"{len(route_data['geometry']['coordinates'])} points, "
                f"{len(first.content) / 1024:.0f} KiB"
            )

            began = time.perf_counter()
            second = client.post("/api/v1/routes/", body, content_type="application/json")
            second_ms = (time.perf_counter() - began) * 1000
            data2 = second.json()
            self._check(
                second.status_code == 200
                and data2["meta"]["cached"] is True
                and data2["meta"]["routing_requests"] == 0,
                f"repeat request served from cache, 0 routing requests ({second_ms:.0f} ms)",
            )

            self.stdout.write("\n3. POST /api/v1/routes/optimize/ (default truck)")
            began = time.perf_counter()
            third = client.post("/api/v1/routes/optimize/", body, content_type="application/json")
            third_ms = (time.perf_counter() - began) * 1000
            self._check(third.status_code == 200, f"HTTP {third.status_code} in {third_ms:.0f} ms")
            if third.status_code == 200:
                plan = third.json()["fuel_plan"]
                self._check(third.json()["meta"]["routing_requests"] == 0, "0 routing requests")
                summary = plan["summary"]
                for stop in plan["stops"]:
                    station = stop["station"]
                    self.stdout.write(
                        f"   mile {stop['route_mile']:>7}: {station['name']}, {station['city']} "
                        f"{station['state']} — {stop['gallons']} gal x ${stop['price_per_gallon']} "
                        f"= ${stop['cost']}"
                    )
                self.stdout.write(
                    f"   consumed {summary['total_gallons_consumed']} gal, bought "
                    f"{summary['total_gallons_purchased']} gal, "
                    f"spent ${summary['total_purchase_cost']}"
                )
            else:
                self.stdout.write(f"   {third.content[:400]!r}")

        if self.failures:
            raise CommandError(f"{self.failures} check(s) failed.")
        self.stdout.write(self.style.SUCCESS("\nAll live checks passed."))

    def _check(self, ok: bool, label: str) -> None:
        if not ok:
            self.failures += 1
        mark = self.style.SUCCESS("PASS") if ok else self.style.ERROR("FAIL")
        self.stdout.write(f"   [{mark}] {label}")
