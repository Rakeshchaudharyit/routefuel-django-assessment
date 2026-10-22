"""Real Django staff/session/CSRF and FuelStation permission boundaries."""

import secrets

import pytest
from django.conf import settings
from django.contrib.auth.models import Permission
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.test import Client, override_settings
from django.urls import reverse

from apps.fuel.models import FuelStation

pytestmark = pytest.mark.django_db


@pytest.fixture
def staff(django_user_model):
    password = secrets.token_urlsafe(24)
    user = django_user_model.objects.create_user("qa-staff", password=password, is_staff=True)
    return user, password


@pytest.fixture
def station():
    return FuelStation.objects.create(
        opis_id=123,
        name="Test station",
        address="I-20",
        city="Dallas",
        state="TX",
        rack_id=1,
        retail_price="3.20",
        max_retail_price="3.50",
    )


def grant(user, *codenames):
    user.user_permissions.add(
        *Permission.objects.filter(content_type__app_label="fuel", codename__in=codenames)
    )


def login(client, staff):
    user, password = staff
    return client.post(reverse("admin:login"), {"username": user.username, "password": password})


def test_root_redirects_to_native_admin(client):
    response = client.get("/")
    assert response.status_code == 302
    assert response.url == "/admin/"


@pytest.mark.parametrize("path", ["/admin/", "/admin/fuel/fuelstation/", "/admin/auth/user/"])
def test_anonymous_admin_pages_require_login(client, path):
    response = client.get(path)
    assert response.status_code == 302
    assert response.url.startswith("/admin/login/?next=")


def test_login_page_has_branding_csrf_labels_and_no_cache(client):
    response = client.get(reverse("admin:login"))
    html = response.content.decode()
    assert response.status_code == 200
    assert "RouteFuel Administration" in html
    assert 'name="csrfmiddlewaretoken"' in html
    assert 'for="id_username"' in html and 'for="id_password"' in html
    assert 'autocomplete="current-password"' in html
    assert 'aria-controls="id_password"' in html
    assert 'id="toggle-password"' in html
    assert "no-store" in response.headers["Cache-Control"]


def test_valid_staff_login_uses_hashed_password_and_restricted_cookie(client, staff):
    response = login(client, staff)
    user, password = staff
    assert response.status_code == 302 and response.url == "/admin/"
    assert client.session["_auth_user_id"] == str(user.pk)
    assert user.password != password and user.check_password(password)
    cookie = response.cookies[settings.SESSION_COOKIE_NAME]
    assert cookie["httponly"]
    assert cookie["samesite"] == "Lax"
    assert cookie["path"] == "/admin/"
    assert cookie["secure"]
    assert client.get("/admin/").status_code == 200


def test_invalid_and_unknown_credentials_have_same_generic_error(client, staff):
    known = login(client, (staff[0], secrets.token_urlsafe(24)))
    unknown = client.post("/admin/login/", {"username": "not-an-account", "password": staff[1]})
    assert known.status_code == unknown.status_code == 200
    assert known.context["form"].non_field_errors() == unknown.context["form"].non_field_errors()
    assert "_auth_user_id" not in client.session


@pytest.mark.parametrize("is_staff,is_active", [(False, True), (True, False)])
def test_nonstaff_and_inactive_accounts_cannot_login_or_access_admin(
    client, staff, is_staff, is_active
):
    user, _ = staff
    user.is_staff, user.is_active = is_staff, is_active
    user.save()
    assert login(client, staff).status_code == 200
    assert "_auth_user_id" not in client.session
    client.force_login(user)
    assert client.get("/admin/").status_code == 302
    assert client.get("/admin/fuel/fuelstation/").status_code == 302


def test_logout_requires_post_and_invalidates_session(client, staff):
    login(client, staff)
    assert client.get("/admin/logout/").status_code == 405
    response = client.post("/admin/logout/")
    assert response.status_code == 200
    assert "_auth_user_id" not in client.session
    assert client.get("/admin/").status_code == 302


def test_login_and_logout_enforce_csrf(staff):
    strict = Client(enforce_csrf_checks=True)
    assert login(strict, staff).status_code == 403
    strict.get("/admin/login/")
    token = strict.cookies[settings.CSRF_COOKIE_NAME].value
    response = strict.post(
        "/admin/login/",
        {"username": staff[0].username, "password": staff[1], "csrfmiddlewaretoken": token},
    )
    assert response.status_code == 302
    assert strict.post("/admin/logout/").status_code == 403
    strict.get("/admin/")
    rotated_token = strict.cookies[settings.CSRF_COOKIE_NAME].value
    assert strict.post("/admin/logout/", {"csrfmiddlewaretoken": rotated_token}).status_code == 200
    assert "_auth_user_id" not in strict.session


def test_login_works_behind_https_proxy_and_still_rejects_foreign_origins(staff):
    # Render terminates TLS: Django receives HTTP plus X-Forwarded-Proto, the browser sends
    # an https:// Origin. Same-origin logins must pass; other origins must still fail CSRF.
    # Browsers always send Host; without it the test client reports "testserver:80".
    proxy = {"HTTP_X_FORWARDED_PROTO": "https", "HTTP_HOST": "testserver"}
    for origin, expected in (("https://testserver", 302), ("https://evil.example", 403)):
        strict = Client(enforce_csrf_checks=True)
        strict.get("/admin/login/", **proxy)
        token = strict.cookies[settings.CSRF_COOKIE_NAME].value
        response = strict.post(
            "/admin/login/",
            {"username": staff[0].username, "password": staff[1], "csrfmiddlewaretoken": token},
            HTTP_ORIGIN=origin,
            **proxy,
        )
        assert response.status_code == expected


def test_login_does_not_redirect_to_external_next_url(client, staff):
    user, password = staff
    response = client.post(
        "/admin/login/?next=https://external.example/",
        {"username": user.username, "password": password, "next": "https://external.example/"},
    )
    assert response.status_code == 302 and response.url == "/admin/"


def test_staff_without_model_permissions_cannot_read_or_edit_stations(client, staff, station):
    login(client, staff)
    for path in [
        "/admin/fuel/fuelstation/",
        f"/admin/fuel/fuelstation/{station.pk}/change/",
        "/admin/fuel/fuelstation/add/",
    ]:
        assert client.get(path).status_code == 403
    assert (
        client.post(f"/admin/fuel/fuelstation/{station.pk}/delete/", {"post": "yes"}).status_code
        == 403
    )
    assert FuelStation.objects.filter(pk=station.pk).exists()


def test_view_permission_is_readonly_and_does_not_grant_user_administration(client, staff, station):
    grant(staff[0], "view_fuelstation")
    login(client, staff)
    response = client.get("/admin/fuel/fuelstation/?q=123&state__exact=TX")
    assert response.status_code == 200 and b"Test station" in response.content
    path = f"/admin/fuel/fuelstation/{station.pk}/change/"
    assert client.get(path).status_code == 200
    assert client.post(path, {"name": "Unauthorized edit"}).status_code == 403
    assert client.get("/admin/auth/user/").status_code == 403
    assert client.get("/admin/fuel/fuelstation/add/").status_code == 403
    station.refresh_from_db()
    assert station.name == "Test station"


def test_change_permission_allows_valid_station_edit_but_not_delete(client, staff, station):
    grant(staff[0], "view_fuelstation", "change_fuelstation")
    login(client, staff)
    response = client.post(
        f"/admin/fuel/fuelstation/{station.pk}/change/",
        {
            "opis_id": station.opis_id,
            "name": "Updated station",
            "address": station.address,
            "city": station.city,
            "state": station.state,
            "rack_id": station.rack_id,
            "retail_price": "3.25",
            "max_retail_price": "3.50",
            "price_observations": 1,
            "geolocation_accuracy": "unresolved",
            "geolocation_source": "",
            "_save": "Save",
        },
    )
    assert response.status_code == 302
    station.refresh_from_db()
    assert station.name == "Updated station"
    assert str(station.retail_price) == "3.25000000"
    assert (
        client.post(f"/admin/fuel/fuelstation/{station.pk}/delete/", {"post": "yes"}).status_code
        == 403
    )


def test_weak_admin_passwords_rejected_by_supported_validators():
    with pytest.raises(ValidationError):
        validate_password("12345678")


def test_https_cookie_configuration_can_be_used_on_local_debug():
    # Runtime settings explicitly protect HTTPS sessions; local examples use DEBUG=true.
    with override_settings(SESSION_COOKIE_SECURE=True, CSRF_COOKIE_SECURE=True):
        response = Client().get("/admin/login/", secure=True)
        assert response.cookies[settings.CSRF_COOKIE_NAME]["secure"]


def test_admin_session_does_not_change_public_api_authentication_or_health(client, staff):
    anonymous = client.get("/api/v1/health/")
    login(client, staff)
    authenticated = client.get("/api/v1/health/")
    assert anonymous.status_code == authenticated.status_code == 200
    assert anonymous.json() == authenticated.json() == {"status": "ok", "service": "routefuel-api"}
    assert settings.REST_FRAMEWORK["DEFAULT_AUTHENTICATION_CLASSES"] == []
    # Public JSON POSTs still work without CSRF; the complete existing routing suite
    # verifies success/error responses against its original contracts.
    strict = Client(enforce_csrf_checks=True)
    for endpoint in ["/api/v1/routes/", "/api/v1/routes/optimize/"]:
        anonymous = strict.post(endpoint, {}, content_type="application/json")
        strict.force_login(staff[0])
        signed_in = strict.post(endpoint, {}, content_type="application/json")
        assert anonymous.status_code == signed_in.status_code == 400
        assert anonymous.json() == signed_in.json()
        assert signed_in.json()["error"]["code"] == "invalid"
        strict.logout()


def test_station_edit_requires_csrf_even_for_authorized_staff(staff, station):
    grant(staff[0], "change_fuelstation")
    strict = Client(enforce_csrf_checks=True)
    strict.force_login(staff[0])
    assert (
        strict.post(
            f"/admin/fuel/fuelstation/{station.pk}/change/", {"name": "Forged change"}
        ).status_code
        == 403
    )
    station.refresh_from_db()
    assert station.name == "Test station"


def test_overview_metrics_are_live_and_use_one_station_aggregate(client, staff, station):
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    grant(staff[0], "view_fuelstation")
    FuelStation.objects.create(
        opis_id=456,
        name="Approximate stop",
        city="Atlanta",
        state="GA",
        rack_id=2,
        retail_price="3.25",
        max_retail_price="3.50",
        latitude=33.7,
        longitude=-84.4,
        geolocation_accuracy="city",
        geolocation_source="census_gazetteer_places_2010",
    )
    login(client, staff)
    with CaptureQueriesContext(connection) as queries:
        response = client.get("/admin/")
    assert response.status_code == 200
    assert response.context["station_metrics"] == {
        "total": 2,
        "approximate": 1,
        "unresolved": 1,
        "states": 2,
    }
    station_queries = [q for q in queries if 'FROM "fuel_fuelstation"' in q["sql"]]
    assert len(station_queries) == 1
    station.delete()
    assert client.get("/admin/").context["station_metrics"]["total"] == 1


def test_overview_does_not_disclose_station_metrics_without_permission(client, staff):
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    login(client, staff)
    with CaptureQueriesContext(connection) as queries:
        response = client.get("/admin/")
    assert "station_metrics" not in response.context
    assert b"Total fuel stations" not in response.content
    assert not any('FROM "fuel_fuelstation"' in q["sql"] for q in queries)
    assert b"/admin/auth/user/" not in response.content
    assert b"http://localhost:3000" in response.content


def test_station_list_keeps_decimal_precision_and_safe_status_badges(client, staff, station):
    from decimal import Decimal

    station.retail_price = Decimal("3.12345678")
    station.save()
    grant(staff[0], "view_fuelstation")
    login(client, staff)
    response = client.get("/admin/fuel/fuelstation/?geolocation_accuracy__exact=unresolved&q=123")
    assert response.status_code == 200
    assert b"$3.12345678" in response.content
    assert b"status-badge status-unresolved" in response.content
    station.refresh_from_db()
    assert station.retail_price == Decimal("3.12345678")


def test_station_form_retains_validation_and_rejects_inconsistent_coordinates(
    client, staff, station
):
    grant(staff[0], "change_fuelstation")
    login(client, staff)
    path = f"/admin/fuel/fuelstation/{station.pk}/change/"
    response = client.get(path)
    for heading in [b"Station Details", b"Fuel Pricing", b"Geolocation", b"Record History"]:
        assert heading in response.content
    response = client.post(
        path,
        {
            "opis_id": station.opis_id,
            "name": station.name,
            "address": station.address,
            "city": station.city,
            "state": station.state,
            "rack_id": station.rack_id,
            "retail_price": "3.20",
            "max_retail_price": "3.50",
            "price_observations": 1,
            "latitude": "32.7",
            "longitude": "-96.8",
            "geolocation_accuracy": "unresolved",
            "geolocation_source": "",
            "_save": "Save",
        },
    )
    assert response.status_code == 200
    assert response.context["adminform"].form.non_field_errors()
    station.refresh_from_db()
    assert not station.has_coordinates


def test_authorized_staff_can_add_station_through_native_form(client, staff):
    grant(staff[0], "add_fuelstation", "view_fuelstation")
    login(client, staff)
    assert client.get("/admin/fuel/fuelstation/add/").status_code == 200
    response = client.post(
        "/admin/fuel/fuelstation/add/",
        {
            "opis_id": 789,
            "name": "New stop",
            "address": "I-20",
            "city": "Dallas",
            "state": "TX",
            "rack_id": 1,
            "retail_price": "3.20",
            "max_retail_price": "3.50",
            "price_observations": 1,
            "geolocation_accuracy": "unresolved",
            "geolocation_source": "",
            "_save": "Save",
        },
    )
    assert response.status_code == 302
    assert FuelStation.objects.filter(opis_id=789, name="New stop").exists()
