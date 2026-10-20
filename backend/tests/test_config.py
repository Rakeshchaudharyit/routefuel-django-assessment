import pytest
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import connection

from config.settings import env_bool, env_float, env_list

LOCAL_APPS = ["apps.core", "apps.routing", "apps.fuel", "apps.optimization"]


def test_local_and_framework_apps_are_installed() -> None:
    for app in ["rest_framework", "corsheaders", *LOCAL_APPS]:
        assert app in settings.INSTALLED_APPS


def test_database_is_sqlite() -> None:
    assert settings.DATABASES["default"]["ENGINE"] == "django.db.backends.sqlite3"


@pytest.mark.django_db
def test_database_connection_works() -> None:
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
        assert cursor.fetchone() == (1,)


def test_settings_read_from_environment() -> None:
    assert settings.DEBUG is False
    assert settings.SECRET_KEY == "test-only-insecure-secret-key"
    assert "testserver" in settings.ALLOWED_HOSTS
    assert settings.CORS_ALLOWED_ORIGINS == ["http://localhost:3000"]
    assert settings.ROUTING_BASE_URL == "https://router.example.test"
    assert settings.ROUTING_TIMEOUT == 5.0


def test_browsable_api_disabled_when_debug_off() -> None:
    renderers = settings.REST_FRAMEWORK["DEFAULT_RENDERER_CLASSES"]

    assert renderers == ["rest_framework.renderers.JSONRenderer"]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("true", True), ("1", True), ("YES", True), ("false", False), ("0", False), ("", False)],
)
def test_env_bool_parses_values(monkeypatch: pytest.MonkeyPatch, raw: str, expected: bool) -> None:
    monkeypatch.setenv("RF_TEST_BOOL", raw)

    assert env_bool("RF_TEST_BOOL", default=not expected) is expected


def test_env_bool_uses_default_and_rejects_garbage(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RF_TEST_BOOL", raising=False)
    assert env_bool("RF_TEST_BOOL", default=True) is True

    monkeypatch.setenv("RF_TEST_BOOL", "maybe")
    with pytest.raises(ImproperlyConfigured):
        env_bool("RF_TEST_BOOL", default=False)


def test_env_list_splits_and_strips(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RF_TEST_LIST", " a.com, b.com ,,")

    assert env_list("RF_TEST_LIST") == ["a.com", "b.com"]


@pytest.mark.parametrize("raw", ["abc", "0", "-3"])
def test_env_float_rejects_invalid_values(monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
    monkeypatch.setenv("RF_TEST_FLOAT", raw)

    with pytest.raises(ImproperlyConfigured):
        env_float("RF_TEST_FLOAT", default=1.0)
