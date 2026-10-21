"""Root URL configuration. All API endpoints are versioned under /api/v1/."""

from django.urls import include, path

api_v1_patterns = [
    path("", include("apps.core.urls")),
    path("", include("apps.routing.urls")),
]

urlpatterns = [
    path("api/v1/", include((api_v1_patterns, "v1"), namespace="v1")),
]
