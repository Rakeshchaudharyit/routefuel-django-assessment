from django.urls import path

from apps.routing.views import OptimizeRouteView, RouteView

urlpatterns = [
    path("routes/", RouteView.as_view(), name="routes"),
    path("routes/optimize/", OptimizeRouteView.as_view(), name="routes-optimize"),
]
