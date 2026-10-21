"""WSGI entry point for the RouteFuel API."""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

application = get_wsgi_application()

# Server processes only (not tests or management commands): load the offline location
# data (~0.3 s) at startup so the first route request doesn't pay for it.
from apps.routing.locations import preload_reference_data  # noqa: E402

preload_reference_data()
