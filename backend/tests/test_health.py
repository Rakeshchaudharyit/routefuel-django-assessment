from unittest.mock import patch

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

HEALTH_URL = "/api/v1/health/"


@pytest.fixture
def api_client() -> APIClient:
    return APIClient()


def test_health_returns_200(api_client: APIClient) -> None:
    response = api_client.get(HEALTH_URL)

    assert response.status_code == 200


def test_health_response_structure(api_client: APIClient) -> None:
    response = api_client.get(HEALTH_URL)

    assert response["Content-Type"] == "application/json"
    assert response.json() == {"status": "ok", "service": "routefuel-api"}


def test_health_reverse_matches_versioned_path(api_client: APIClient) -> None:
    response = api_client.get(reverse("v1:health"))

    assert response.status_code == 200


def test_health_makes_no_external_http_calls(api_client: APIClient) -> None:
    with patch("httpx.Client.send") as send, patch("httpx.AsyncClient.send") as async_send:
        response = api_client.get(HEALTH_URL)

    assert response.status_code == 200
    send.assert_not_called()
    async_send.assert_not_called()


def test_health_does_not_touch_database(api_client: APIClient) -> None:
    # No ``django_db`` mark: pytest-django raises if the view opens a DB connection.
    response = api_client.get(HEALTH_URL)

    assert response.status_code == 200


def test_health_rejects_unsupported_method_with_error_envelope(api_client: APIClient) -> None:
    response = api_client.post(HEALTH_URL, {}, format="json")

    assert response.status_code == 405
    body = response.json()
    assert body["error"]["code"] == "method_not_allowed"
    assert "POST" in body["error"]["message"]
    assert body["error"]["details"] is None
