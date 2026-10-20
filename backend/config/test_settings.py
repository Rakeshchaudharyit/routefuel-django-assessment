"""Settings used by pytest. Deterministic and independent of any local .env."""

import os

# Set before importing the base settings so they are never read from .env.
os.environ["DJANGO_SECRET_KEY"] = "test-only-insecure-secret-key"  # noqa: S105
os.environ["DJANGO_DEBUG"] = "false"
os.environ["DJANGO_ALLOWED_HOSTS"] = "testserver,localhost"
os.environ["DJANGO_CORS_ALLOWED_ORIGINS"] = "http://localhost:3000"
os.environ["ROUTING_BASE_URL"] = "https://router.example.test"
os.environ["ROUTING_TIMEOUT"] = "5"

from config.settings import *  # noqa: E402, F403

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}
