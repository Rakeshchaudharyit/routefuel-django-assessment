import math
from io import StringIO
from pathlib import Path

import pytest
from django.core.management import CommandError, call_command
from django.db import IntegrityError, transaction

from apps.fuel.geolocation import (
    Gazetteer,
    GazetteerError,
    MatchStatus,
    Place,
    geolocate_stations,
    place_key,
    strip_descriptors,
    validate_coordinates,
)
from apps.fuel.importer import import_fuel_prices
from apps.fuel.models import FuelStation, GeolocationAccuracy, GeolocationSource


@pytest.fixture
def gazetteer(sample_gazetteer: Path) -> Gazetteer:
    return Gazetteer.from_file(sample_gazetteer)


# --- name normalisation -------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Tomah city", "Tomah"),
        ("Carson City", "Carson City"),  # "City" is part of the name, not a descriptor
        ("Boise City city", "Boise City"),
        ("Indianapolis city (balance)", "Indianapolis"),
        ("Highland CDP", "Highland"),
        ("Juneau city and borough", "Juneau"),
    ],
)
def test_strip_descriptors(raw: str, expected: str) -> None:
    assert strip_descriptors(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("St. Paul", "SAINT PAUL"),
        ("Ft Worth", "FORT WORTH"),
        ("Mt. Vernon", "MOUNT VERNON"),
        ("Winston-Salem", "WINSTON SALEM"),
        ("Cañon City", "CANON CITY"),
        ("  big   cabin ", "BIG CABIN"),
    ],
)
def test_place_key(raw: str, expected: str) -> None:
    assert place_key(raw) == expected


# --- gazetteer lookups ----------------------------------------------------------


def test_gazetteer_loads_latin1_file(gazetteer: Gazetteer) -> None:
    assert len(gazetteer) == 11
    assert gazetteer.lookup("Canon City", "NM").status is MatchStatus.MATCHED


@pytest.mark.parametrize(
    ("city", "state"),
    [
        ("Tomah", "WI"),
        ("TOMAH", "WI"),
        ("Carson City", "NV"),
        ("Boise", "ID"),  # official name "Boise City"
        ("Indianapolis", "IN"),  # consolidated city "(balance)"
        ("Mc Calla", "AL"),  # spacing variant of "McCalla"
        ("Saint Paul", "MN"),  # "St. Paul"
    ],
)
def test_lookup_matches_known_variants(gazetteer: Gazetteer, city: str, state: str) -> None:
    assert gazetteer.lookup(city, state).status is MatchStatus.MATCHED


def test_lookup_requires_matching_state(gazetteer: Gazetteer) -> None:
    assert gazetteer.lookup("Tomah", "MN").status is MatchStatus.NOT_FOUND


def test_lookup_reports_ambiguous_names(gazetteer: Gazetteer) -> None:
    match = gazetteer.lookup("Highland", "IN")

    assert match.status is MatchStatus.AMBIGUOUS
    assert match.place is None


def test_uncertainty_radius_follows_land_area() -> None:
    small = Place("A", "WI", 1.0, 1.0, land_area_sq_miles=0.1)
    large = Place("B", "WI", 1.0, 1.0, land_area_sq_miles=361.4)

    assert small.uncertainty_miles == 1.0  # floor
    assert large.uncertainty_miles == round(math.sqrt(361.4 / math.pi), 1)


def test_missing_gazetteer_file(tmp_path: Path) -> None:
    with pytest.raises(GazetteerError, match="not found"):
        Gazetteer.from_file(tmp_path / "none.txt")


def test_gazetteer_with_missing_columns(tmp_path: Path) -> None:
    path = tmp_path / "bad.txt"
    path.write_text("USPS\tNAME\nWI\tTomah city\n", encoding="latin-1")

    with pytest.raises(GazetteerError, match="INTPTLAT"):
        Gazetteer.from_file(path)


def test_gazetteer_with_bad_number(tmp_path: Path) -> None:
    path = tmp_path / "bad.txt"
    path.write_text(
        "USPS\tNAME\tALAND_SQMI\tINTPTLAT\tINTPTLONG\nWI\tTomah city\t7.9\tnorth\t-90.5\n",
        encoding="latin-1",
    )

    with pytest.raises(GazetteerError, match="line 2"):
        Gazetteer.from_file(path)


# --- coordinate validation ------------------------------------------------------


@pytest.mark.parametrize(
    ("lat", "lng"), [(91, 0), (-90.1, 0), (0, 181), (0, -180.5), (math.nan, 0), (0, math.inf)]
)
def test_validate_coordinates_rejects_out_of_range(lat: float, lng: float) -> None:
    with pytest.raises(ValueError):
        validate_coordinates(lat, lng)


def test_validate_coordinates_accepts_limits() -> None:
    validate_coordinates(90, 180)
    validate_coordinates(-90, -180)


# --- geolocating stations -------------------------------------------------------


@pytest.mark.django_db
def test_geolocate_resolves_matches_and_leaves_others_unresolved(
    sample_csv: Path, gazetteer: Gazetteer
) -> None:
    import_fuel_prices(sample_csv)

    result = geolocate_stations(gazetteer)

    assert (result.considered, result.resolved, result.ambiguous, result.not_found) == (6, 4, 1, 1)
    tomah = FuelStation.objects.get(opis_id=9)
    assert (tomah.latitude, tomah.longitude) == (43.988465, -90.501813)
    assert tomah.geolocation_accuracy == GeolocationAccuracy.CITY
    assert tomah.geolocation_source == GeolocationSource.CENSUS_GAZETTEER_PLACES_2010
    assert tomah.location_uncertainty_miles == round(math.sqrt(7.9 / math.pi), 1)

    unknown = FuelStation.objects.get(opis_id=44)
    assert unknown.geolocation_accuracy == GeolocationAccuracy.UNRESOLVED
    assert unknown.latitude is None and unknown.longitude is None
    assert unknown.geolocation_source == GeolocationSource.NONE


@pytest.mark.django_db
def test_geolocate_rerun_only_considers_unresolved(sample_csv: Path, gazetteer: Gazetteer) -> None:
    import_fuel_prices(sample_csv)
    geolocate_stations(gazetteer)

    rerun = geolocate_stations(gazetteer)

    assert (rerun.considered, rerun.resolved) == (2, 0)
    assert FuelStation.objects.filter(geolocation_accuracy=GeolocationAccuracy.CITY).count() == 4


@pytest.mark.django_db
def test_geolocate_force_recomputes_city_level(sample_csv: Path, gazetteer: Gazetteer) -> None:
    import_fuel_prices(sample_csv)
    geolocate_stations(gazetteer)

    assert geolocate_stations(gazetteer, force=True).considered == 6


@pytest.mark.django_db
def test_geolocate_never_overwrites_address_level(write_csv, gazetteer: Gazetteer) -> None:
    import_fuel_prices(write_csv([["1", "A", "B", "Tomah", "WI", "1", "3.1"]]))
    FuelStation.objects.update(
        latitude=43.9,
        longitude=-90.4,
        geolocation_accuracy=GeolocationAccuracy.ADDRESS,
        geolocation_source="manual",
    )

    result = geolocate_stations(gazetteer, force=True)

    assert result.considered == 0
    assert FuelStation.objects.get().latitude == 43.9


@pytest.mark.django_db
def test_geolocate_stations_command(sample_csv: Path, sample_gazetteer: Path) -> None:
    import_fuel_prices(sample_csv)
    out = StringIO()

    call_command("geolocate_stations", gazetteer=sample_gazetteer, stdout=out)

    assert "Resolved (city-level):   4" in out.getvalue()
    assert "Highland, IN (ambiguous)" in out.getvalue()


@pytest.mark.django_db
def test_geolocate_stations_command_missing_file(tmp_path: Path) -> None:
    with pytest.raises(CommandError, match="not found"):
        call_command("geolocate_stations", gazetteer=tmp_path / "x.txt", stdout=StringIO())


# --- database constraints -------------------------------------------------------


def _station(**overrides: object) -> FuelStation:
    values: dict[str, object] = {
        "opis_id": 1,
        "name": "A",
        "city": "Tomah",
        "state": "WI",
        "rack_id": 1,
        "retail_price": "3.10",
        "max_retail_price": "3.10",
    }
    values.update(overrides)
    return FuelStation(**values)


@pytest.mark.django_db
@pytest.mark.parametrize(
    "overrides",
    [
        {"latitude": 43.9, "longitude": -90.5},  # coordinates on an unresolved station
        {"geolocation_accuracy": GeolocationAccuracy.CITY},  # resolved without coordinates
        {"latitude": 95.0, "longitude": -90.5, "geolocation_accuracy": GeolocationAccuracy.CITY},
        {"latitude": 43.9, "longitude": -190.0, "geolocation_accuracy": GeolocationAccuracy.CITY},
        {"retail_price": "0"},
        {"retail_price": "3.50", "max_retail_price": "3.10"},
    ],
)
def test_database_rejects_inconsistent_station(overrides: dict[str, object]) -> None:
    with pytest.raises(IntegrityError), transaction.atomic():
        _station(**overrides).save()
