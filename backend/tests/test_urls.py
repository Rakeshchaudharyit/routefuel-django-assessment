import pytest
from django.urls import Resolver404, resolve, reverse

from apps.core.views import HealthView


def test_health_url_reverses_to_versioned_path() -> None:
    assert reverse("v1:health") == "/api/v1/health/"


def test_health_url_resolves_to_health_view() -> None:
    match = resolve("/api/v1/health/")

    assert match.func.view_class is HealthView
    assert match.namespace == "v1"
    assert match.url_name == "health"


@pytest.mark.parametrize("path", ["/health/", "/api/health/", "/api/v2/health/"])
def test_unversioned_or_unknown_paths_do_not_resolve(path: str) -> None:
    with pytest.raises(Resolver404):
        resolve(path)
