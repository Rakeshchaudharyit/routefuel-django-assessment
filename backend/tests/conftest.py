import csv
import socket
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from apps.fuel.importer import REQUIRED_COLUMNS

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def block_network(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Fail any test that tries to open a network connection."""

    def guard(*args: object, **kwargs: object) -> None:
        raise RuntimeError("Network access is not allowed in tests.")

    monkeypatch.setattr(socket.socket, "connect", guard)
    monkeypatch.setattr(socket, "create_connection", guard)
    yield


@pytest.fixture(autouse=True)
def fresh_route_memos() -> Iterator[None]:
    """Per-process route/station reuse must never leak between tests."""
    from apps.routing.fuel_plans import clear_memos

    clear_memos()
    yield
    clear_memos()


@pytest.fixture
def sample_csv() -> Path:
    return FIXTURES / "fuel_prices_sample.csv"


@pytest.fixture
def sample_gazetteer() -> Path:
    return FIXTURES / "gazetteer_sample.txt"


VALID_ROW = ["1", "TEST STOP", "I-1, EXIT 1", "Tomah", "WI", "420", "3.25"]


@pytest.fixture
def write_csv(tmp_path: Path) -> Callable[..., Path]:
    """Write rows (lists of cells) to a CSV with the standard header."""

    def _write(rows: list[list[str]], header: tuple[str, ...] = REQUIRED_COLUMNS) -> Path:
        path = tmp_path / "prices.csv"
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(header)
            writer.writerows(rows)
        return path

    return _write
