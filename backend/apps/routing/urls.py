from django.urls import path

from apps.routing.views import RouteView

urlpatterns = [
    path("routes/", RouteView.as_view(), name="routes"),
]
