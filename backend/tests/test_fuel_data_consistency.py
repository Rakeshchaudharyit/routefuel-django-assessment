"""Geolocation must give identical results on every database, survive interruption, and
the read-only data report must fingerprint the data without writing anything."""

import re
from io import StringIO
from pathlib import Path

import pytest
from django.core.management import call_command
from django.db import DatabaseError, OperationalError
from django.db import connection as default_connection
from django.test.utils import CaptureQueriesContext

from apps.fuel import geolocation
from apps.fuel.geolocation import Gazetteer, geolocate_stations
from apps.fuel.management.commands.fuel_data_report import read_only
from apps.fuel.models import FuelStation, GeolocationAccuracy

pytestmark = pytest.mark.django_db

# Six cities the sample gazetteer resolves (two via fallbacks), one ambiguous, one unknown.
CITIES = [
    ("Big Cabin", "OK"),
    ("Tomah", "WI"),
    ("Gila Bend", "AZ"),
    ("Carson City", "NV"),
    ("Boise", "ID"),  # -> "Boise City"
    ("Mc Calla", "AL"),  # -> "McCalla"
    ("Highland", "IN"),  # ambiguous: town and CDP
    ("Nowhere", "TX"),  # not in the gazetteer
]
RESOLVABLE = 6 * 3


class NetworkedDatabase:
    """Stands in for ``connection`` so the PostgreSQL write path runs on the test database."""

    vendor = "postgresql"


class LocalDatabase:
    """Stands in for ``connection`` so the SQLite write path runs on any test database."""

    vendor = "sqlite"


@pytest.fixture
def gazetteer(sample_gazetteer: Path) -> Gazetteer:
    return Gazetteer.from_file(sample_gazetteer)


@pytest.fixture
def stations() -> None:
    for number, (city, state) in enumerate(CITIES * 3, start=1):
        FuelStation.objects.create(
            opis_id=number,
            name=f"STOP {number}",
            address="I-1, EXIT 1",
            city=city,
            state=state,
            rack_id=1,
            retail_price="3.000",
            max_retail_price="3.000",
        )


def snapshot() -> list[tuple]:
    return list(
        FuelStation.objects.order_by("opis_id").values_list(
            "opis_id",
            "latitude",
            "longitude",
            "geolocation_accuracy",
            "geolocation_source",
            "location_uncertainty_miles",
        )
    )


def unresolve_all() -> None:
    FuelStation.objects.update(
        latitude=None,
        longitude=None,
        geolocation_source="",
        geolocation_accuracy=GeolocationAccuracy.UNRESOLVED,
        location_uncertainty_miles=None,
    )


def updates_in(queries: CaptureQueriesContext) -> int:
    sql = (query["sql"].lstrip().upper() for query in queries.captured_queries)
    return sum(1 for statement in sql if statement.startswith("UPDATE"))


@pytest.mark.usefixtures("stations")
def test_networked_write_path_produces_identical_rows(gazetteer, monkeypatch) -> None:
    geolocate_stations(gazetteer)
    local = snapshot()
    assert sum(row[3] == GeolocationAccuracy.CITY for row in local) == RESOLVABLE

    unresolve_all()
    monkeypatch.setattr(geolocation, "connection", NetworkedDatabase())
    result = geolocate_stations(gazetteer)

    assert result.resolved == RESOLVABLE
    assert snapshot() == local
    geolocate_stations(gazetteer, force=True)  # the --force path also matches
    assert snapshot() == local


@pytest.mark.usefixtures("stations")
def test_networked_write_path_needs_one_statement_per_batch(gazetteer, monkeypatch) -> None:
    # Regression: one UPDATE per matched place meant ~3,500 network round trips on Neon.
    monkeypatch.setattr(geolocation, "connection", LocalDatabase())
    with CaptureQueriesContext(default_connection) as local:
        geolocate_stations(gazetteer)
    assert updates_in(local) == 6  # SQLite keeps one cheap UPDATE per place

    unresolve_all()
    monkeypatch.setattr(geolocation, "connection", NetworkedDatabase())
    with CaptureQueriesContext(default_connection) as networked:
        geolocate_stations(gazetteer)
    assert updates_in(networked) == 1


@pytest.mark.usefixtures("stations")
def test_interrupted_geolocation_writes_nothing_and_a_rerun_completes(
    gazetteer, monkeypatch
) -> None:
    monkeypatch.setattr(geolocation, "connection", NetworkedDatabase())

    def connection_lost(*args, **kwargs):
        raise OperationalError("server closed the connection unexpectedly")

    monkeypatch.setattr(FuelStation.objects, "bulk_update", connection_lost)
    with pytest.raises(OperationalError):
        geolocate_stations(gazetteer)
    assert {row[3] for row in snapshot()} == {GeolocationAccuracy.UNRESOLVED}

    monkeypatch.undo()
    assert geolocate_stations(gazetteer).resolved == RESOLVABLE
    rerun = geolocate_stations(gazetteer)
    assert (rerun.considered, rerun.resolved) == (6, 0)  # only the genuinely unresolved


@pytest.mark.usefixtures("stations")
def test_address_level_coordinates_are_never_overwritten(gazetteer) -> None:
    FuelStation.objects.filter(opis_id=1).update(
        latitude=36.5, longitude=-95.2, geolocation_accuracy=GeolocationAccuracy.ADDRESS
    )
    geolocate_stations(gazetteer, force=True)

    station = FuelStation.objects.get(opis_id=1)
    assert (station.latitude, station.longitude) == (36.5, -95.2)
    assert station.geolocation_accuracy == GeolocationAccuracy.ADDRESS


@pytest.mark.usefixtures("stations")
def test_geolocate_stations_dry_run_writes_nothing(settings, sample_gazetteer) -> None:
    settings.GAZETTEER_PLACES_PATH = sample_gazetteer
    before = snapshot()
    out = StringIO()

    call_command("geolocate_stations", "--dry-run", stdout=out)

    assert "DRY RUN" in out.getvalue()
    assert f"Resolved (city-level):   {RESOLVABLE}" in out.getvalue()
    assert snapshot() == before


def report(settings, sample_gazetteer, sample_csv, *args: str) -> str:
    settings.GAZETTEER_PLACES_PATH = sample_gazetteer
    settings.FUEL_PRICES_CSV_PATH = sample_csv
    out = StringIO()
    call_command("fuel_data_report", *args, stdout=out)
    return out.getvalue()


def field(text: str, label: str) -> str:
    return re.search(rf"{re.escape(label)}:\s+(\S+)", text).group(1)


@pytest.mark.usefixtures("stations")
def test_fuel_data_report_counts_fingerprints_and_examples(
    settings, sample_gazetteer, sample_csv, gazetteer
) -> None:
    before = report(settings, sample_gazetteer, sample_csv)
    assert field(before, "Unresolved") == str(len(CITIES) * 3)
    assert field(before, "Unresolved the gazetteer resolves") == str(RESOLVABLE)

    geolocate_stations(gazetteer)
    after = report(settings, sample_gazetteer, sample_csv, "--opis-id", "1", "--opis-id", "999")

    assert field(after, "Total") == "24"
    assert field(after, "With coordinates") == str(RESOLVABLE)
    assert field(after, "Unresolved") == "6"
    assert field(after, "Inconsistent rows") == "0"
    assert field(after, "Unresolved the gazetteer resolves") == "0"
    assert field(after, "City-level points that differ") == "0"
    assert field(after, "Station data") == field(before, "Station data")
    assert field(after, "Geolocation") != field(before, "Geolocation")
    assert "1 STOP 1, Big Cabin, OK: lat=36.540187 lng=-95.222116 accuracy=city" in after
    assert "999: not in this database" in after
    assert report(settings, sample_gazetteer, sample_csv, "--opis-id", "1") == after.replace(
        "  999: not in this database\n", ""
    )


@pytest.mark.usefixtures("stations")
def test_fuel_data_report_writes_nothing(settings, sample_gazetteer, sample_csv) -> None:
    before = list(FuelStation.objects.values_list("id", "updated_at"))
    report(settings, sample_gazetteer, sample_csv)
    assert list(FuelStation.objects.values_list("id", "updated_at")) == before

    with pytest.raises(DatabaseError):  # SQLite: OperationalError; PostgreSQL: InternalError
        with read_only():
            FuelStation.objects.update(name="WRITE ATTEMPT")
    FuelStation.objects.filter(opis_id=1).update(name="WRITABLE AGAIN")  # restored afterwards
