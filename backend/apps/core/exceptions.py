"""Consistent JSON error envelope for every DRF-handled API error."""

from __future__ import annotations

import logging
from typing import Any

from django.http import Http404
from rest_framework.exceptions import APIException
from rest_framework.response import Response
from rest_framework.views import exception_handler, set_rollback

logger = logging.getLogger(__name__)


class ApiError(APIException):
    """An API error with a specific status, machine-readable code and optional details."""

    def __init__(self, *, status_code: int, code: str, message: str, details: Any = None) -> None:
        self.status_code = status_code
        self.default_code = code
        self.details = details
        super().__init__(detail=message, code=code)


def api_exception_handler(exc: Exception, context: dict[str, Any]) -> Response | None:
    """Wrap DRF error responses as ``{"error": {"code", "message", "details"}}``.

    Unhandled exceptions are logged with their traceback and answered with a generic 500 in
    the same envelope, so clients never receive an HTML error page or internal details.
    """
    response = exception_handler(exc, context)
    if response is None:
        logger.error("Unhandled API error", exc_info=exc)
        set_rollback()
        return Response(
            {
                "error": {
                    "code": "internal_error",
                    "message": "An unexpected error occurred. Please try again later.",
                    "details": None,
                }
            },
            status=500,
        )

    if isinstance(exc, Http404):
        code = "not_found"
    elif isinstance(exc, APIException):
        code = exc.default_code
    else:
        code = "error"

    data = response.data
    if isinstance(data, dict) and set(data) == {"detail"}:
        message = str(data["detail"])
        details = getattr(exc, "details", None)
    else:
        message = "The request could not be processed."
        details = data

    response.data = {"error": {"code": code, "message": message, "details": details}}
    return response
