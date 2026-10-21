from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.exceptions import ApiError
from apps.optimization.optimizer import InfeasiblePlan, Vehicle
from apps.routing.fuel_plans import fuel_plan_payload, plan_route_with_fuel
from apps.routing.locations import LocationError, ResolvedLocation
from apps.routing.providers import OsrmProvider, RoutingError
from apps.routing.serializers import OptimizeRequestSerializer, RouteRequestSerializer
from apps.routing.services import RoutePlan, SameLocationError, plan_route


@contextmanager
def _domain_errors() -> Iterator[None]:
    """Translate service-layer exceptions into the API error envelope."""
    try:
        yield
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
    except InfeasiblePlan as exc:
        raise ApiError(
            status_code=422,
            code="no_feasible_fuel_plan",
            message=exc.message,
            details={
                "from_mile": round(exc.from_mile, 1),
                "to_mile": round(exc.to_mile, 1),
                "gap_miles": round(exc.to_mile - exc.from_mile, 1),
                "max_reach_miles": round(exc.reach_miles, 1),
            },
        ) from exc


class RouteView(APIView):
    """``POST /api/v1/routes/`` — driving route between two US locations."""

    def post(self, request: Request) -> Response:
        serializer = RouteRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        with _domain_errors():
            plan = plan_route(data["start"], data["finish"])
        return Response(route_plan_payload(plan))


class OptimizeRouteView(APIView):
    """``POST /api/v1/routes/optimize/`` — route plus a minimum-cost fuel plan."""

    def post(self, request: Request) -> Response:
        serializer = OptimizeRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        vehicle_input = data["vehicle"]
        vehicle = Vehicle(
            range_miles=vehicle_input["range_miles"],
            mpg=vehicle_input["mpg"],
            starting_fuel_gallons=vehicle_input["starting_fuel_gallons"],
        )
        with _domain_errors():
            result = plan_route_with_fuel(
                data["start"],
                data["finish"],
                vehicle,
                starting_fuel_price=vehicle_input["starting_fuel_price_per_gallon"],
            )
        payload = route_plan_payload(result.route_plan)
        payload.update(fuel_plan_payload(result))
        payload["meta"] = {**payload.pop("meta"), "timings_ms": result.timings_ms}
        return Response(payload)


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
