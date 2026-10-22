"""
Django settings for the RouteFuel API.

All deployment-specific values are read from environment variables (optionally
loaded from a ``.env`` file at the repository root). See ``.env.example``.
"""

from __future__ import annotations

import math
import os
from pathlib import Path
from typing import Any

import dj_database_url
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.core.validators import URLValidator
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
    if not math.isfinite(value) or value <= 0:
        raise ImproperlyConfigured(f"{name} must be finite and greater than zero, got {raw!r}.")
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
    "apps.core.admin_apps.RouteFuelAdminConfig",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.humanize",
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
    # Serves collected static files (admin CSS/JS) when DEBUG is false, e.g. on Render.
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# --------------------------------------------------------------------------
# Database
# --------------------------------------------------------------------------



def database_config() -> dict[str, Any]:
    """PostgreSQL (e.g. Neon) from ``DATABASE_URL``; local SQLite only when it is unset.

    A malformed or non-PostgreSQL URL is an error, never a silent SQLite fallback. On Render
    (which sets ``RENDER=true`` at build and run time) a missing URL is also an error, so
    ``migrate`` can never run against a throwaway SQLite file there.
    """
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        if env_bool("RENDER", default=False):
            raise ImproperlyConfigured("DATABASE_URL must be set on Render.")
        return {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db.sqlite3"}
    try:
        config = dj_database_url.parse(url, conn_max_age=60, conn_health_checks=True)
    except Exception:
        # Never echo the URL or the parser message: the URL contains the password.
        raise ImproperlyConfigured("DATABASE_URL is not a valid database URL.") from None
    if config.get("ENGINE") != "django.db.backends.postgresql":
        raise ImproperlyConfigured("DATABASE_URL must use the postgres:// or postgresql:// scheme.")
    if not config.get("HOST") or not config.get("NAME"):
        raise ImproperlyConfigured("DATABASE_URL must include a host and a database name.")
    options = config.setdefault("OPTIONS", {})
    options.setdefault("sslmode", "require")  # Neon requires TLS; a sslmode in the URL wins.
    options.setdefault("connect_timeout", 10)
    return config


DATABASES = {"default": database_config()}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --------------------------------------------------------------------------
# Internationalization & static files
# --------------------------------------------------------------------------

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = False
USE_TZ = True

STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    # Hashed, compressed copies built by collectstatic; WhiteNoise serves them with far-future
    # caching. With DEBUG on, Django serves the unhashed source files as before.
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

# Admin uses Django's database sessions and default password hashers. Public DRF views
# retain their explicit empty authentication classes and never consume admin sessions.
ROUTEFUEL_DASHBOARD_URL = os.environ.get("ROUTEFUEL_DASHBOARD_URL", "http://localhost:3000").strip()
try:
    URLValidator(schemes=["http", "https"])(ROUTEFUEL_DASHBOARD_URL)
except ValidationError as exc:
    raise ImproperlyConfigured("ROUTEFUEL_DASHBOARD_URL must be an HTTP(S) URL.") from exc
LOGIN_URL = "admin:login"
LOGIN_REDIRECT_URL = "admin:index"
SESSION_COOKIE_NAME = "routefuel_admin_sessionid"
SESSION_COOKIE_PATH = "/admin/"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_AGE = 8 * 60 * 60
SESSION_COOKIE_SECURE = env_bool("DJANGO_SECURE_COOKIES", default=not DEBUG)
# Render terminates TLS and forwards plain HTTP with X-Forwarded-Proto set by its proxy. Trusting
# it lets Django see admin requests as HTTPS, so CSRF origin checks match https:// origins.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
CSRF_COOKIE_SECURE = SESSION_COOKIE_SECURE
CSRF_COOKIE_SAMESITE = "Lax"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 12},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

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
