"""Consistent JSON error envelope for every DRF-handled API error."""

from __future__ import annotations

from typing import Any

from django.http import Http404
from rest_framework.exceptions import APIException
from rest_framework.response import Response
from rest_framework.views import exception_handler


def api_exception_handler(exc: Exception, context: dict[str, Any]) -> Response | None:
    """Wrap DRF error responses as ``{"error": {"code", "message", "details"}}``.

    Unhandled exceptions return ``None`` so Django produces a standard 500.
    """
    response = exception_handler(exc, context)
    if response is None:
        return None

    if isinstance(exc, Http404):
        code = "not_found"
    elif isinstance(exc, APIException):
        code = exc.default_code
    else:
        code = "error"

    data = response.data
    if isinstance(data, dict) and set(data) == {"detail"}:
        message = str(data["detail"])
        details = None
    else:
        message = "The request could not be processed."
        details = data

    response.data = {"error": {"code": code, "message": message, "details": details}}
    return response
