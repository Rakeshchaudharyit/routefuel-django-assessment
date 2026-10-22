import pytest
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import connection

from config.settings import database_config, env_bool, env_float, env_list

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


NEON_STYLE_URL = "postgresql://rf_user:s3cret-pw@ep-example-pooler.us-east-2.aws.neon.tech/neondb"


def test_database_config_uses_sqlite_without_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("RENDER", raising=False)

    assert database_config()["ENGINE"] == "django.db.backends.sqlite3"


def test_database_config_uses_postgresql_with_ssl(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", NEON_STYLE_URL)

    config = database_config()

    assert config["ENGINE"] == "django.db.backends.postgresql"
    assert config["HOST"] == "ep-example-pooler.us-east-2.aws.neon.tech"
    assert config["NAME"] == "neondb"
    assert config["OPTIONS"]["sslmode"] == "require"
    assert config["CONN_HEALTH_CHECKS"] is True


def test_database_config_keeps_sslmode_from_url(monkeypatch: pytest.MonkeyPatch) -> None:
    url = NEON_STYLE_URL + "?sslmode=verify-full&channel_binding=require"
    monkeypatch.setenv("DATABASE_URL", url)

    options = database_config()["OPTIONS"]

    assert options["sslmode"] == "verify-full"
    assert options["channel_binding"] == "require"


@pytest.mark.parametrize(
    "url",
    [
        "not-a-url",
        "postgresql//rf_user:s3cret-pw@host/neondb",
        "postgresql://rf_user:s3cret-pw@host:notaport/neondb",
        "mysql://rf_user:s3cret-pw@host/neondb",
        "sqlite:///db.sqlite3",
        "postgresql://rf_user:s3cret-pw@/neondb",
        "postgresql://rf_user:s3cret-pw@host/",
    ],
)
def test_database_config_rejects_bad_urls_without_leaking_them(
    monkeypatch: pytest.MonkeyPatch, url: str
) -> None:
    monkeypatch.setenv("DATABASE_URL", url)

    with pytest.raises(ImproperlyConfigured) as excinfo:
        database_config()

    assert "s3cret-pw" not in str(excinfo.value)
    assert excinfo.value.__cause__ is None


def test_database_config_requires_database_url_on_render(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("RENDER", "true")

    with pytest.raises(ImproperlyConfigured, match="DATABASE_URL must be set on Render"):
        database_config()


def test_proxy_ssl_header_trusts_render_forwarded_proto() -> None:
    assert settings.SECURE_PROXY_SSL_HEADER == ("HTTP_X_FORWARDED_PROTO", "https")
