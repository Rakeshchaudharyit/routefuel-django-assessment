"""Settings used by pytest. Deterministic and independent of any local .env."""

import os

# Set before importing the base settings so they are never read from .env.
os.environ["DJANGO_SECRET_KEY"] = "test-only-insecure-secret-key"  # noqa: S105
os.environ["DJANGO_DEBUG"] = "false"
os.environ["DJANGO_SECURE_COOKIES"] = "true"
os.environ["ROUTEFUEL_DASHBOARD_URL"] = "http://localhost:3000"
os.environ["DJANGO_ALLOWED_HOSTS"] = "testserver,localhost"
os.environ["DJANGO_CORS_ALLOWED_ORIGINS"] = "http://localhost:3000"
os.environ["ROUTING_BASE_URL"] = "https://router.example.test"
os.environ["ROUTING_TIMEOUT"] = "5"
os.environ["ROUTING_USER_AGENT"] = "RouteFuel-tests/1.0"
os.environ["ROUTE_CACHE_TTL"] = "3600"
os.environ["FUEL_CORRIDOR_MILES"] = "5"
# Empty (not unset) so a DATABASE_URL in a local .env is never loaded for tests.
os.environ["DATABASE_URL"] = ""

from config.settings import *  # noqa: E402, F403

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

# Tests render admin templates with DEBUG off but never run collectstatic, so use the plain
# storage (no hashed-manifest lookup) instead of the production WhiteNoise manifest storage.
STORAGES = {
    **STORAGES,  # noqa: F405
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

# Per-process memory cache: fast and isolated; tests clear it between cases.
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
