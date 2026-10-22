"""Staff administration and the unchanged public versioned API."""

from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

admin.site.site_title = "RouteFuel Administration"
admin.site.site_header = "RouteFuel"
admin.site.index_title = "Operations Administration"
admin.site.site_url = None

api_v1_patterns = [
    path("", include("apps.core.urls")),
    path("", include("apps.routing.urls")),
]

urlpatterns = [
    path("", RedirectView.as_view(pattern_name="admin:index", permanent=False), name="home"),
    path("admin/", admin.site.urls),
    path("api/v1/", include((api_v1_patterns, "v1"), namespace="v1")),
]
