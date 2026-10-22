"""Request validation for the routes endpoint (shape and ranges only; no lookups)."""

from __future__ import annotations

import math
from decimal import Decimal, InvalidOperation
from typing import Any

from rest_framework import serializers

from apps.routing.locations import CoordinateQuery, LocationQuery, PlaceQuery

MAX_PLACE_LENGTH = 120
_COORDINATE_KEYS = {"latitude", "longitude"}
_RANGES = {"latitude": (-90.0, 90.0), "longitude": (-180.0, 180.0)}


class LocationField(serializers.Field):
    """``"City, ST"`` or ``{"latitude": float, "longitude": float}``."""

    default_error_messages = {
        "type": 'Expected "City, ST" or an object with "latitude" and "longitude".',
    }

    def to_internal_value(self, data: Any) -> LocationQuery:
        if isinstance(data, str):
            return self._place(data)
        if isinstance(data, dict):
            return self._coordinates(data)
        self.fail("type")

    def to_representation(self, value: Any) -> Any:
        return value

    def _place(self, data: str) -> PlaceQuery:
        text = " ".join(data.split())
        if not text:
            raise serializers.ValidationError("This field may not be blank.", code="blank")
        if len(text) > MAX_PLACE_LENGTH:
            raise serializers.ValidationError(
                f"Ensure this field has no more than {MAX_PLACE_LENGTH} characters.",
                code="max_length",
            )
        city, sep, state = text.rpartition(",")
        city, state = city.strip(" ,"), state.strip()
        if not sep or not city or not state:
            raise serializers.ValidationError(
                'Use the format "City, ST" (for example "Dallas, TX").', code="format"
            )
        return PlaceQuery(city=city, state=state)

    def _coordinates(self, data: dict[str, Any]) -> CoordinateQuery:
        errors: dict[str, list[str]] = {}
        unknown = sorted(set(data) - _COORDINATE_KEYS)
        if unknown:
            errors["non_field_errors"] = [f"Unexpected keys: {', '.join(unknown)}."]
        values: dict[str, float] = {}
        for key, (low, high) in _RANGES.items():
            value = data.get(key)
            if value is None:
                errors[key] = ["This field is required."]
            elif isinstance(value, bool) or not isinstance(value, int | float):
                errors[key] = ["A number is required."]
            elif not low <= value <= high or not math.isfinite(value):
                errors[key] = [f"{key.capitalize()} must be between {low:g} and {high:g}."]
            else:
                values[key] = float(value)
        if errors:
            raise serializers.ValidationError(errors)
        return CoordinateQuery(latitude=values["latitude"], longitude=values["longitude"])


class RouteRequestSerializer(serializers.Serializer):
    start = LocationField()
    finish = LocationField()
    # "simplified" returns a lighter line for drawing; distances and fuel-stop mile markers
    # are always computed from the full provider geometry.
    geometry_detail = serializers.ChoiceField(choices=["full", "simplified"], default="full")


DEFAULT_RANGE_MILES = 500.0
DEFAULT_MPG = 10.0
MAX_RANGE_MILES = 5000.0
MAX_MPG = 200.0
MIN_FUEL_PRICE = Decimal("0.50")
MAX_FUEL_PRICE = Decimal("20.00")
_VEHICLE_KEYS = {"range_miles", "mpg", "starting_fuel_gallons", "starting_fuel_price_per_gallon"}


def _strict_number(value: Any, name: str, errors: dict[str, list[str]]) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        errors[name] = ["A number is required."]
        return None
    try:
        number = float(value)
    except OverflowError:
        number = float("inf")
    if not math.isfinite(number):
        errors[name] = ["A finite number is required."]
        return None
    return number


class VehicleField(serializers.Field):
    """Optional vehicle settings; omitted values take the assessment defaults."""

    default_error_messages = {"type": "Expected an object."}

    def to_internal_value(self, data: Any) -> dict[str, Any]:
        if not isinstance(data, dict):
            self.fail("type")
        errors: dict[str, list[str]] = {}
        unknown = sorted(set(data) - _VEHICLE_KEYS)
        if unknown:
            errors["non_field_errors"] = [f"Unexpected keys: {', '.join(unknown)}."]

        range_miles = DEFAULT_RANGE_MILES
        mpg = DEFAULT_MPG
        if "range_miles" in data:
            value = _strict_number(data["range_miles"], "range_miles", errors)
            if value is not None and not 0 < value <= MAX_RANGE_MILES:
                errors["range_miles"] = [f"Must be greater than 0 and at most {MAX_RANGE_MILES:g}."]
            elif value is not None:
                range_miles = value
        if "mpg" in data:
            value = _strict_number(data["mpg"], "mpg", errors)
            if value is not None and not 0 < value <= MAX_MPG:
                errors["mpg"] = [f"Must be greater than 0 and at most {MAX_MPG:g}."]
            elif value is not None:
                mpg = value

        capacity = range_miles / mpg
        if not math.isfinite(capacity) or capacity <= 0:
            errors["mpg"] = ["Range and MPG must produce a finite, positive tank capacity."]
            raise serializers.ValidationError(errors)
        starting_fuel = capacity
        if "starting_fuel_gallons" in data:
            value = _strict_number(data["starting_fuel_gallons"], "starting_fuel_gallons", errors)
            if value is not None and not 0 <= value <= capacity + 1e-9:
                errors["starting_fuel_gallons"] = [
                    f"Must be between 0 and the tank capacity ({capacity:g} gallons = "
                    "range_miles / mpg)."
                ]
            elif value is not None:
                starting_fuel = min(value, capacity)

        starting_price = None
        if data.get("starting_fuel_price_per_gallon") is not None:
            starting_price = self._price(data["starting_fuel_price_per_gallon"], errors)

        if errors:
            raise serializers.ValidationError(errors)
        return {
            "range_miles": range_miles,
            "mpg": mpg,
            "starting_fuel_gallons": starting_fuel,
            "starting_fuel_price_per_gallon": starting_price,
        }

    def to_representation(self, value: Any) -> Any:
        return value

    @staticmethod
    def _price(value: Any, errors: dict[str, list[str]]) -> Decimal | None:
        key = "starting_fuel_price_per_gallon"
        if isinstance(value, bool) or not isinstance(value, int | float | str):
            errors[key] = ["A number or decimal string is required."]
            return None
        try:
            price = Decimal(str(value).strip())
        except InvalidOperation:
            errors[key] = ["A number or decimal string is required."]
            return None
        if not price.is_finite() or not MIN_FUEL_PRICE <= price <= MAX_FUEL_PRICE:
            errors[key] = [f"Must be between {MIN_FUEL_PRICE} and {MAX_FUEL_PRICE} USD."]
            return None
        if -price.as_tuple().exponent > 8:
            errors[key] = ["Use at most 8 decimal places."]
            return None
        return price


MAX_STOP_SAVINGS = Decimal("1000.00")


class StopPolicyField(serializers.Field):
    """Optional practical-stop policy: ``{"min_savings_per_stop": "5.00"}`` (USD)."""

    default_error_messages = {"type": "Expected an object."}

    def to_internal_value(self, data: Any) -> Decimal:
        if not isinstance(data, dict):
            self.fail("type")
        unknown = sorted(set(data) - {"min_savings_per_stop"})
        if unknown:
            raise serializers.ValidationError(
                {"non_field_errors": [f"Unexpected keys: {', '.join(unknown)}."]}
            )
        value = data.get("min_savings_per_stop")
        message = {
            "min_savings_per_stop": [
                f"Must be a USD amount above 0 and at most {MAX_STOP_SAVINGS}, "
                "with at most 2 decimal places."
            ]
        }
        if isinstance(value, bool) or not isinstance(value, int | float | str):
            raise serializers.ValidationError(message)
        try:
            amount = Decimal(str(value).strip())
        except InvalidOperation as exc:
            raise serializers.ValidationError(message) from exc
        if (
            not amount.is_finite()
            or not 0 < amount <= MAX_STOP_SAVINGS
            or -amount.as_tuple().exponent > 2
        ):
            raise serializers.ValidationError(message)
        return amount.quantize(Decimal("0.01"))

    def to_representation(self, value: Any) -> Any:
        return value


class OptimizeRequestSerializer(RouteRequestSerializer):
    vehicle = VehicleField(required=False)
    stop_policy = StopPolicyField(required=False, allow_null=True)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        attrs.setdefault("vehicle", VehicleField().to_internal_value({}))
        return attrs
