from __future__ import annotations

from typing import Any

from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.exceptions import ApiError
from apps.routing.locations import LocationError, ResolvedLocation
from apps.routing.providers import OsrmProvider, RoutingError
from apps.routing.serializers import RouteRequestSerializer
from apps.routing.services import RoutePlan, SameLocationError, plan_route


class RouteView(APIView):
    """``POST /api/v1/routes/`` — driving route between two US locations."""

    def post(self, request: Request) -> Response:
        serializer = RouteRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            data = serializer.validated_data
            plan = plan_route(data["start"], data["finish"])
        except LocationError as exc:
            raise ApiError(
                status_code=422,
                code=exc.code,
                message=exc.message,
                details={"field": exc.field, **exc.details},
            ) from exc
        except SameLocationError as exc:
            raise ApiError(status_code=422, code="same_location", message=str(exc)) from exc
        except RoutingError as exc:
            raise ApiError(status_code=exc.status_code, code=exc.code, message=exc.message) from exc
        return Response(route_plan_payload(plan))


def _location_payload(location: ResolvedLocation) -> dict[str, Any]:
    return {
        "label": location.label,
        "latitude": location.latitude,
        "longitude": location.longitude,
        "state": location.state,
        "source": location.source,
    }


def route_plan_payload(plan: RoutePlan) -> dict[str, Any]:
    route = plan.route
    return {
        "origin": _location_payload(plan.origin),
        "destination": _location_payload(plan.destination),
        "route": {
            "distance_miles": round(route.distance_miles, 2),
            "duration_minutes": round(route.duration_minutes, 1),
            "geometry": route.geometry,
        },
        "meta": {
            "provider": route.provider,
            "attribution": OsrmProvider.attribution if route.provider == OsrmProvider.name else "",
            "cached": plan.cached,
            "routing_requests": plan.routing_requests,
        },
    }
