"""Root URL configuration. All API endpoints are versioned under /api/v1/."""

from django.urls import include, path

api_v1_patterns = [
    path("", include("apps.core.urls")),
    # M1–M4 mount their endpoints here, e.g. the route-plan endpoint.
]

urlpatterns = [
    path("api/v1/", include((api_v1_patterns, "v1"), namespace="v1")),
]
