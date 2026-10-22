"""M7 regressions for reproduced numeric validation failures, not new API features."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import httpx
import pytest
from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured
from rest_framework.test import APIClient

from apps.routing import services
from apps.routing.providers import OsrmProvider, RoutingProviderError
from config.settings import env_float
from tests.test_routing_api import FakeOsrm, osrm_ok


@pytest.fixture
def client() -> APIClient:
    return APIClient()


@pytest.fixture
def osrm(monkeypatch: pytest.MonkeyPatch) -> FakeOsrm:
    fake = FakeOsrm()
    monkeypatch.setattr(services, "get_routing_provider", fake.provider)
    return fake


@pytest.fixture(autouse=True)
def clear_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.mark.parametrize("raw", ["nan", "NaN", "inf", "-inf", "1e309"])
def test_environment_numbers_must_be_finite(monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
    monkeypatch.setenv("RF_QA_FLOAT", raw)
    with pytest.raises(ImproperlyConfigured):
        env_float("RF_QA_FLOAT", 1.0)


@pytest.mark.django_db
@pytest.mark.parametrize("url", ["/api/v1/routes/", "/api/v1/routes/optimize/"])
@pytest.mark.parametrize("field", ["latitude", "longitude"])
def test_oversized_coordinate_is_a_field_error(
    client: APIClient, osrm: FakeOsrm, url: str, field: str
) -> None:
    start = {"latitude": 32.794176, "longitude": -96.765503, field: 10**400}
    response = client.post(url, {"start": start, "finish": "Atlanta, GA"}, format="json")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid"
    assert field in response.json()["error"]["details"]["start"]
    assert not osrm.requests


@pytest.mark.django_db
@pytest.mark.parametrize("field", ["range_miles", "mpg", "starting_fuel_gallons"])
def test_oversized_vehicle_number_is_a_field_error(
    client: APIClient, osrm: FakeOsrm, field: str
) -> None:
    response = client.post(
        "/api/v1/routes/optimize/",
        {"start": "Dallas, TX", "finish": "Atlanta, GA", "vehicle": {field: 10**400}},
        format="json",
    )
    assert response.status_code == 400
    assert field in response.json()["error"]["details"]["vehicle"]
    assert not osrm.requests


@pytest.mark.django_db
@pytest.mark.parametrize("vehicle", [{"mpg": 1e-320}, {"range_miles": 5e-324, "mpg": 200}])
def test_unrepresentable_tank_capacity_rejected_before_routing(
    client: APIClient, osrm: FakeOsrm, vehicle: dict[str, float]
) -> None:
    response = client.post(
        "/api/v1/routes/optimize/",
        {"start": "Dallas, TX", "finish": "Atlanta, GA", "vehicle": vehicle},
        format="json",
    )
    assert response.status_code == 400
    assert "vehicle" in response.json()["error"]["details"]
    assert not osrm.requests


@pytest.mark.parametrize("field", ["distance", "duration", "coordinates"])
def test_oversized_provider_number_is_a_provider_error(field: str) -> None:
    body: dict[str, Any] = deepcopy(osrm_ok())
    if field == "coordinates":
        body["routes"][0]["geometry"]["coordinates"][0][0] = 10**400
    else:
        body["routes"][0][field] = 10**400
    response = httpx.Response(200, json=body)
    provider = OsrmProvider("https://example.test", timeout=5, user_agent="RouteFuel/test")
    with pytest.raises(RoutingProviderError):
        provider._parse(response)
