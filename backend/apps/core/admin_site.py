"""Presentation context for the native Django admin; authentication stays inherited."""

from django.conf import settings
from django.contrib.admin import AdminSite
from django.db.models import Count, Q

from apps.fuel.models import FuelStation, GeolocationAccuracy


class RouteFuelAdminSite(AdminSite):
    index_template = "admin/operations_index.html"

    def each_context(self, request):
        context = super().each_context(request)
        context["route_planner_url"] = settings.ROUTEFUEL_DASHBOARD_URL
        return context

    def index(self, request, extra_context=None):
        context = dict(extra_context or {})
        station_admin = self._registry[FuelStation]
        # A single aggregate query, only on the overview and only for permitted staff.
        if station_admin.has_view_permission(request):
            context["station_metrics"] = FuelStation.objects.aggregate(
                total=Count("pk"),
                approximate=Count("pk", filter=Q(geolocation_accuracy=GeolocationAccuracy.CITY)),
                unresolved=Count(
                    "pk", filter=Q(geolocation_accuracy=GeolocationAccuracy.UNRESOLVED)
                ),
                states=Count("state", distinct=True, filter=~Q(state="")),
            )
        return super().index(request, extra_context=context)
