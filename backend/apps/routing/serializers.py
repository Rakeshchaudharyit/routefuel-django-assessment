"""Request validation for the routes endpoint (shape and ranges only; no lookups)."""

from __future__ import annotations

import math
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
            elif not math.isfinite(value) or not low <= value <= high:
                errors[key] = [f"{key.capitalize()} must be between {low:g} and {high:g}."]
            else:
                values[key] = float(value)
        if errors:
            raise serializers.ValidationError(errors)
        return CoordinateQuery(latitude=values["latitude"], longitude=values["longitude"])


class RouteRequestSerializer(serializers.Serializer):
    start = LocationField()
    finish = LocationField()
