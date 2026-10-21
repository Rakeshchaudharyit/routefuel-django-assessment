"""Route planning: resolve both ends, then one cached provider request."""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass

from django.conf import settings
from django.core.cache import cache
from django.db import DatabaseError

from apps.routing.locations import (
    LocationError,
    LocationQuery,
    ResolvedLocation,
    resolve_location,
)
from apps.routing.providers import Coordinate, Route, RoutingProvider, get_routing_provider

logger = logging.getLogger(__name__)

CACHE_KEY_VERSION = "v1"
CACHE_COORDINATE_DECIMALS = 5  # ~1.1 m; inputs closer than this share a cached route


class SameLocationError(Exception):
    pass


@dataclass(frozen=True)
class RoutePlan:
    origin: ResolvedLocation
    destination: ResolvedLocation
    route: Route
    cached: bool
    routing_requests: int  # external routing calls made for this response (0 or 1)


def plan_route(
    start: LocationQuery, finish: LocationQuery, *, provider: RoutingProvider | None = None
) -> RoutePlan:
    resolved = {}
    for field, query in (("start", start), ("finish", finish)):
        try:
            resolved[field] = resolve_location(query)
        except LocationError as exc:
            exc.field = field
            raise
    origin, destination = resolved["start"], resolved["finish"]
    if _rounded(origin) == _rounded(destination):
        raise SameLocationError("Start and finish resolve to the same location.")

    provider = provider or get_routing_provider()
    key = route_cache_key(provider, origin, destination)
    cached = _cache_get(key)
    if cached is not None:
        return RoutePlan(origin, destination, cached, cached=True, routing_requests=0)

    route = provider.route(
        Coordinate(origin.latitude, origin.longitude),
        Coordinate(destination.latitude, destination.longitude),
    )
    _cache_set(key, route)
    return RoutePlan(origin, destination, route, cached=False, routing_requests=1)


def _rounded(location: ResolvedLocation) -> tuple[float, float]:
    return (
        round(location.latitude, CACHE_COORDINATE_DECIMALS),
        round(location.longitude, CACHE_COORDINATE_DECIMALS),
    )


def route_cache_key(
    provider: RoutingProvider, origin: ResolvedLocation, destination: ResolvedLocation
) -> str:
    """Deterministic key: provider identity + coordinates rounded to ~1 m. Direction matters."""
    identity = getattr(provider, "base_url", "") + "/" + getattr(provider, "profile", "")
    (o_lat, o_lon), (d_lat, d_lon) = _rounded(origin), _rounded(destination)
    raw = f"{provider.name}|{identity}|{o_lat:.5f},{o_lon:.5f}|{d_lat:.5f},{d_lon:.5f}"
    digest = hashlib.sha256(raw.encode()).hexdigest()[:32]
    return f"route:{CACHE_KEY_VERSION}:{digest}"


def _cache_get(key: str) -> Route | None:
    try:
        data = cache.get(key)
    except DatabaseError:
        logger.warning("Route cache read failed; continuing without cache.", exc_info=True)
        return None
    if not isinstance(data, dict):
        return None
    try:
        return Route(**data)
    except TypeError:
        return None  # stale shape from an older version; refetch


def _cache_set(key: str, route: Route) -> None:
    data = {
        "distance_meters": route.distance_meters,
        "duration_seconds": route.duration_seconds,
        "geometry": route.geometry,
        "provider": route.provider,
    }
    try:
        cache.set(key, data, timeout=settings.ROUTE_CACHE_TTL)
    except DatabaseError:
        logger.warning("Route cache write failed; response is still returned.", exc_info=True)
