"""
Django settings for the RouteFuel API.

All deployment-specific values are read from environment variables (optionally
loaded from a ``.env`` file at the repository root). See ``.env.example``.
"""

from __future__ import annotations

import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent  # backend/
REPO_ROOT = BASE_DIR.parent

# Real environment variables always win over values in the .env file.
load_dotenv(REPO_ROOT / ".env", override=False)

_TRUE_VALUES = {"1", "true", "yes", "on"}
_FALSE_VALUES = {"0", "false", "no", "off", ""}


def env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in _TRUE_VALUES:
        return True
    if value in _FALSE_VALUES:
        return False
    raise ImproperlyConfigured(f"{name} must be a boolean (true/false), got {raw!r}.")


def env_list(name: str, default: str = "") -> list[str]:
    raw = os.environ.get(name, default)
    return [item.strip() for item in raw.split(",") if item.strip()]


def env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise ImproperlyConfigured(f"{name} must be a number, got {raw!r}.") from exc
    if value <= 0:
        raise ImproperlyConfigured(f"{name} must be greater than zero, got {raw!r}.")
    return value


def env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ImproperlyConfigured(f"{name} must be an integer, got {raw!r}.") from exc
    if value <= 0:
        raise ImproperlyConfigured(f"{name} must be greater than zero, got {raw!r}.")
    return value


# --------------------------------------------------------------------------
# Core
# --------------------------------------------------------------------------

# Safe default: debug is OFF unless explicitly enabled.
DEBUG = env_bool("DJANGO_DEBUG", default=False)

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")
if not SECRET_KEY:
    if not DEBUG:
        raise ImproperlyConfigured(
            "DJANGO_SECRET_KEY must be set when DJANGO_DEBUG is false. "
            "Copy .env.example to .env for local development."
        )
    SECRET_KEY = "django-insecure-local-development-only"  # noqa: S105

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", default="localhost,127.0.0.1")

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django.contrib.staticfiles",
    # Third party
    "rest_framework",
    "corsheaders",
    # Local
    "apps.core",
    "apps.routing",
    "apps.fuel",
    "apps.optimization",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
            ],
        },
    },
]

# --------------------------------------------------------------------------
# Database
# --------------------------------------------------------------------------

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --------------------------------------------------------------------------
# Internationalization & static files
# --------------------------------------------------------------------------

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = False
USE_TZ = True

STATIC_URL = "static/"

# --------------------------------------------------------------------------
# Django REST Framework
# --------------------------------------------------------------------------

_renderers = ["rest_framework.renderers.JSONRenderer"]
if DEBUG:
    _renderers.append("rest_framework.renderers.BrowsableAPIRenderer")

REST_FRAMEWORK = {
    # Public, read-only assessment API: no authentication layer.
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.AllowAny"],
    "UNAUTHENTICATED_USER": None,
    "DEFAULT_RENDERER_CLASSES": _renderers,
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    "EXCEPTION_HANDLER": "apps.core.exceptions.api_exception_handler",
}

# --------------------------------------------------------------------------
# CORS (for the future Next.js dashboard)
# --------------------------------------------------------------------------

CORS_ALLOWED_ORIGINS = env_list(
    "DJANGO_CORS_ALLOWED_ORIGINS", default="http://localhost:3000,http://127.0.0.1:3000"
)
CORS_URLS_REGEX = r"^/api/.*$"

# --------------------------------------------------------------------------
# Cache. Database-backed so cached routes survive restarts without extra
# infrastructure; the table is created by the routing app's migration.
# --------------------------------------------------------------------------

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.db.DatabaseCache",
        "LOCATION": "routefuel_cache",
        "OPTIONS": {"MAX_ENTRIES": 5000},
    }
}

# --------------------------------------------------------------------------
# Routing provider (M2)
# --------------------------------------------------------------------------

ROUTING_BASE_URL = os.environ.get("ROUTING_BASE_URL", "https://router.project-osrm.org").rstrip("/")
ROUTING_TIMEOUT = env_float("ROUTING_TIMEOUT", default=10.0)
# The OSRM demo-server policy requires an identifying User-Agent.
ROUTING_USER_AGENT = os.environ.get(
    "ROUTING_USER_AGENT", "RouteFuel/0.2 (Spotter AI assessment; Django route planner)"
).strip()
if not ROUTING_USER_AGENT:
    raise ImproperlyConfigured("ROUTING_USER_AGENT must not be blank.")
ROUTE_CACHE_TTL = env_int("ROUTE_CACHE_TTL", default=7 * 24 * 60 * 60)

# --------------------------------------------------------------------------
# Fuel-stop optimisation (M3)
# --------------------------------------------------------------------------

# A station counts as "on the route" when its point is within this distance of the route line,
# plus the station's own location uncertainty (M1 city-level points mark the town, not the pump).
FUEL_CORRIDOR_MILES = env_float("FUEL_CORRIDOR_MILES", default=5.0)

# --------------------------------------------------------------------------
# Fuel data (M1). Files live in the repository; nothing is fetched at runtime.
# --------------------------------------------------------------------------

FUEL_PRICES_CSV_PATH = BASE_DIR / "data" / "fuel-prices-for-be-assessment.csv"
GAZETTEER_PLACES_PATH = BASE_DIR / "data" / "reference" / "Gaz_places_national.txt"
US_STATE_BOUNDARIES_PATH = BASE_DIR / "data" / "reference" / "us_states_ne_10m.geojson"

# --------------------------------------------------------------------------
# Logging
# --------------------------------------------------------------------------

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "INFO"},
    # Replace Django's default "django" logger so records are emitted once, via root.
    "loggers": {"django": {"handlers": [], "level": "INFO", "propagate": True}},
}
