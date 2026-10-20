from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

SERVICE_NAME = "routefuel-api"


class HealthView(APIView):
    """Liveness check. Deliberately touches no database or external service."""

    def get(self, request: Request) -> Response:
        return Response({"status": "ok", "service": SERVICE_NAME})
