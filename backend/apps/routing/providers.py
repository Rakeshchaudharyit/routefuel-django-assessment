"""Routing-provider boundary.

The rest of the app depends only on ``RoutingProvider.route()`` and the ``Route`` it
returns, so another engine (Valhalla, GraphHopper, a self-hosted OSRM) can be swapped in
by adding a class here. ``OsrmProvider`` makes exactly one HTTP request per call and never
retries: on a public, rate-limited demo server a retry storm is worse than a clean error.
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Protocol

import httpx
from django.conf import settings

logger = logging.getLogger(__name__)

METERS_PER_MILE = 1609.344  # international mile, exact


@dataclass(frozen=True)
class Coordinate:
    latitude: float
    longitude: float


class Route:
    """A normalised route. Geometry is a GeoJSON LineString of ``[longitude, latitude]``.

    The geometry is held as parsed data, as compact JSON text, or both, and each form is built
    from the other only when first needed. Cached routes are stored as text, so a cache hit
    can be sent to the client without re-encoding tens of thousands of coordinates.
    """

    __slots__ = ("distance_meters", "duration_seconds", "provider", "_geometry", "_geometry_json")

    def __init__(
        self,
        distance_meters: float,
        duration_seconds: float,
        geometry: dict[str, Any] | None = None,
        provider: str = "",
        *,
        geometry_json: str | None = None,
    ) -> None:
        if geometry is None and geometry_json is None:
            raise ValueError("A route needs geometry or geometry_json.")
        self.distance_meters = distance_meters
        self.duration_seconds = duration_seconds
        self.provider = provider
        self._geometry = geometry
        self._geometry_json = geometry_json

    @property
    def geometry(self) -> dict[str, Any]:
        if self._geometry is None:
            self._geometry = json.loads(self._geometry_json)
        return self._geometry

    @property
    def geometry_json(self) -> str:
        if self._geometry_json is None:
            self._geometry_json = json.dumps(self._geometry, separators=(",", ":"))
        return self._geometry_json

    @property
    def distance_miles(self) -> float:
        return self.distance_meters / METERS_PER_MILE

    @property
    def duration_minutes(self) -> float:
        return self.duration_seconds / 60


class RoutingError(Exception):
    """Base class. ``code``/``status_code`` map directly onto the API error envelope."""

    code = "routing_error"
    status_code = 502

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class RouteNotFound(RoutingError):
    code = "route_not_found"
    status_code = 422


class RoutingTimeout(RoutingError):
    code = "routing_timeout"
    status_code = 504


class RoutingUnavailable(RoutingError):
    code = "routing_unavailable"
    status_code = 503


class RoutingProviderError(RoutingError):
    code = "routing_provider_error"
    status_code = 502


class RoutingProvider(Protocol):
    name: str

    def route(self, origin: Coordinate, destination: Coordinate) -> Route: ...


class OsrmProvider:
    """Client for the OSRM HTTP API ``route`` service (v5)."""

    name = "osrm"
    attribution = "Routing © OSRM; map data © OpenStreetMap contributors (ODbL)"

    def __init__(
        self,
        base_url: str,
        *,
        timeout: float,
        user_agent: str,
        profile: str = "driving",
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.profile = profile
        # One pooled client per provider: building a client loads the CA bundle (~50 ms measured)
        # and a kept-alive connection skips repeat TLS handshakes. httpx.Client is thread-safe.
        self._client = httpx.Client(
            timeout=httpx.Timeout(timeout, connect=min(timeout, 5.0)),
            headers={"User-Agent": user_agent, "Accept": "application/json"},
            transport=transport,  # injected in tests
        )

    def route(self, origin: Coordinate, destination: Coordinate) -> Route:
        coords = (
            f"{origin.longitude:.6f},{origin.latitude:.6f};"
            f"{destination.longitude:.6f},{destination.latitude:.6f}"
        )
        url = f"{self.base_url}/route/v1/{self.profile}/{coords}"
        params = {
            "overview": "full",
            "geometries": "geojson",
            "steps": "false",
            "alternatives": "false",
            "annotations": "false",
        }
        try:
            response = self._client.get(url, params=params)
        except httpx.TimeoutException as exc:
            logger.warning("OSRM request timed out: %s", exc)
            raise RoutingTimeout("The routing provider did not respond in time.") from exc
        except httpx.HTTPError as exc:
            logger.warning("OSRM request failed: %s", exc)
            raise RoutingUnavailable("The routing provider could not be reached.") from exc
        return self._parse(response)

    def _parse(self, response: httpx.Response) -> Route:
        status = response.status_code
        try:
            body = response.json()
        except ValueError:
            body = None
        osrm_code = body.get("code") if isinstance(body, dict) else None

        # OSRM reports routing failures as HTTP 400 with a JSON "code".
        if osrm_code in ("NoRoute", "NoSegment") and status in (200, 400):
            if osrm_code == "NoSegment":
                raise RouteNotFound("A location is too far from any drivable road.")
            raise RouteNotFound("No driving route exists between these locations.")
        if status == 429:
            raise RoutingUnavailable("The routing provider is rate limiting requests.")
        if status >= 500:
            logger.warning("OSRM returned HTTP %s", status)
            raise RoutingUnavailable(f"The routing provider returned HTTP {status}.")
        if status != 200:
            logger.warning("OSRM returned HTTP %s (code=%s)", status, osrm_code)
            raise RoutingProviderError(
                f"The routing provider rejected the request (HTTP {status}"
                + (f", {osrm_code})." if osrm_code else ").")
            )
        if body is None:
            raise RoutingProviderError("The routing provider returned invalid JSON.")
        if osrm_code != "Ok":
            raise RoutingProviderError(f"Unexpected routing provider status: {osrm_code!r}.")
        return _route_from_osrm(body, provider=self.name)


def _route_from_osrm(body: dict[str, Any], *, provider: str) -> Route:
    try:
        route = body["routes"][0]
        distance = float(route["distance"])
        duration = float(route["duration"])
        geometry = route["geometry"]
        coordinates = geometry["coordinates"]
        geometry_type = geometry["type"]
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise RoutingProviderError("The routing provider response is missing route data.") from exc

    if not (math.isfinite(distance) and math.isfinite(duration)) or distance < 0 or duration < 0:
        raise RoutingProviderError("The routing provider returned an invalid distance or duration.")
    if geometry_type != "LineString" or not isinstance(coordinates, list) or len(coordinates) < 2:
        raise RoutingProviderError("The routing provider returned invalid route geometry.")
    try:
        positions = [[float(lon), float(lat)] for lon, lat in coordinates]
    except (TypeError, ValueError) as exc:
        raise RoutingProviderError("The routing provider returned invalid route geometry.") from exc
    if not all(-180 <= lon <= 180 and -90 <= lat <= 90 for lon, lat in positions):
        raise RoutingProviderError("The routing provider returned out-of-range coordinates.")

    return Route(
        distance_meters=distance,
        duration_seconds=duration,
        geometry={"type": "LineString", "coordinates": positions},
        provider=provider,
    )


@lru_cache(maxsize=1)
def get_routing_provider() -> RoutingProvider:
    return OsrmProvider(
        settings.ROUTING_BASE_URL,
        timeout=settings.ROUTING_TIMEOUT,
        user_agent=settings.ROUTING_USER_AGENT,
    )
