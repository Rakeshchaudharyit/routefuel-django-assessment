from decimal import Decimal
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import pytest
from django.core.management import CommandError, call_command
from django.db import IntegrityError

from apps.fuel.importer import CsvFormatError, Reason, import_fuel_prices, parse_price
from apps.fuel.models import FuelStation, GeolocationAccuracy
from tests.conftest import VALID_ROW

pytestmark = pytest.mark.django_db


def row(**overrides: str) -> list[str]:
    keys = ["id", "name", "address", "city", "state", "rack", "price"]
    values = dict(zip(keys, VALID_ROW, strict=True))
    values.update(overrides)
    return [values[k] for k in keys]


# --- successful import -------------------------------------------------------


def test_sample_import_counts(sample_csv: Path) -> None:
    result = import_fuel_prices(sample_csv)

    assert result.total_rows == 9
    assert result.valid_rows == 8
    assert result.rejected == []
    assert result.skipped_by_reason == {"non_us_station": 1}
    assert result.duplicate_rows_merged == 2
    assert result.stations_in_file == 6
    assert (result.inserted, result.updated, result.unchanged) == (6, 0, 0)
    assert FuelStation.objects.count() == 6


def test_imported_fields_are_normalised(sample_csv: Path) -> None:
    import_fuel_prices(sample_csv)

    station = FuelStation.objects.get(opis_id=44)
    assert station.city == "Unknownville"  # surrounding whitespace removed
    assert station.state == "NE"
    assert station.rack_id == 300
    assert station.address == "I-80, EXIT 1"


def test_price_precision_is_preserved_exactly(sample_csv: Path) -> None:
    import_fuel_prices(sample_csv)

    station = FuelStation.objects.get(opis_id=7)
    assert station.retail_price == Decimal("3.00733333")
    assert isinstance(station.retail_price, Decimal)


def test_imported_stations_start_without_coordinates(sample_csv: Path) -> None:
    import_fuel_prices(sample_csv)

    assert not FuelStation.objects.exclude(geolocation_accuracy=GeolocationAccuracy.UNRESOLVED)
    assert not FuelStation.objects.filter(latitude__isnull=False).exists()


def test_utf8_bom_header_is_accepted(tmp_path: Path) -> None:
    path = tmp_path / "bom.csv"
    path.write_text(
        "﻿OPIS Truckstop ID,Truckstop Name,Address,City,State,Rack ID,Retail Price\n"
        "1,A,B,Tomah,WI,1,3.1\n",
        encoding="utf-8",
    )

    assert import_fuel_prices(path).inserted == 1


# --- validation --------------------------------------------------------------


@pytest.mark.parametrize(
    "price",
    ["abc", "", "-3.10", "0", "0.10", "25.00", "NaN", "Infinity", "3.123456789"],
)
def test_invalid_prices_are_rejected(write_csv, price: str) -> None:
    path = write_csv([row(id="1", price=price), row(id="2")])

    result = import_fuel_prices(path)

    assert len(result.rejected) == 1
    assert result.rejected[0].opis_id == "1"
    expected = Reason.MISSING_FIELD if price == "" else Reason.INVALID_PRICE
    assert result.rejected[0].reason is expected
    assert list(FuelStation.objects.values_list("opis_id", flat=True)) == [2]


def test_parse_price_accepts_boundaries_and_eight_decimals() -> None:
    assert parse_price("0.50") == Decimal("0.50")
    assert parse_price("20.00") == Decimal("20.00")
    assert parse_price("3.12345678") == Decimal("3.12345678")


@pytest.mark.parametrize("column", ["id", "name", "city", "state", "rack"])
def test_missing_required_field_is_rejected(write_csv, column: str) -> None:
    path = write_csv([row(**{column: "   "})])

    result = import_fuel_prices(path)

    assert [issue.reason for issue in result.rejected] == [Reason.MISSING_FIELD]
    assert FuelStation.objects.count() == 0


@pytest.mark.parametrize("address", ["", ",", " - "])
def test_blank_address_is_kept_with_a_warning(write_csv, address: str) -> None:
    result = import_fuel_prices(write_csv([row(address=address)]))

    assert result.inserted == 1
    assert result.warnings_by_reason == {"incomplete_address": 1}
    assert FuelStation.objects.get().address == ""


@pytest.mark.parametrize("state", ["ZZ", "XX", "Wisconsin", "W1"])
def test_invalid_state_codes_are_rejected(write_csv, state: str) -> None:
    result = import_fuel_prices(write_csv([row(state=state)]))

    assert [issue.reason for issue in result.rejected] == [Reason.INVALID_STATE]


def test_lowercase_state_is_normalised(write_csv) -> None:
    import_fuel_prices(write_csv([row(state="wi")]))

    assert FuelStation.objects.get().state == "WI"


def test_canadian_rows_are_skipped_not_rejected(write_csv) -> None:
    result = import_fuel_prices(write_csv([row(id="1", state="ON"), row(id="2")]))

    assert result.rejected == []
    assert result.skipped_by_reason == {"non_us_station": 1}
    assert FuelStation.objects.count() == 1


@pytest.mark.parametrize("value", ["abc", "0", "-5", "1.5", "99999999999"])
def test_invalid_station_id_is_rejected(write_csv, value: str) -> None:
    result = import_fuel_prices(write_csv([row(id=value)]))

    assert [issue.reason for issue in result.rejected] == [Reason.INVALID_ID]


def test_invalid_rack_id_is_rejected(write_csv) -> None:
    result = import_fuel_prices(write_csv([row(rack="R12")]))

    assert [issue.reason for issue in result.rejected] == [Reason.INVALID_RACK_ID]


def test_malformed_rows_are_rejected_and_others_imported(write_csv) -> None:
    path = write_csv([[*row(id="1"), "extra"], row(id="2")[:4], row(id="3")])

    result = import_fuel_prices(path)

    assert [issue.reason for issue in result.rejected] == [Reason.MALFORMED_ROW] * 2
    assert [issue.line for issue in result.rejected] == [2, 3]
    assert list(FuelStation.objects.values_list("opis_id", flat=True)) == [3]


def test_missing_columns_abort_before_any_write(write_csv) -> None:
    path = write_csv([["1", "A"]], header=("OPIS Truckstop ID", "Truckstop Name"))

    with pytest.raises(CsvFormatError, match="Retail Price"):
        import_fuel_prices(path)
    assert FuelStation.objects.count() == 0


def test_missing_file_raises_format_error(tmp_path: Path) -> None:
    with pytest.raises(CsvFormatError, match="not found"):
        import_fuel_prices(tmp_path / "nope.csv")


def test_non_utf8_file_raises_format_error(tmp_path: Path) -> None:
    path = tmp_path / "latin.csv"
    path.write_bytes(
        b"OPIS Truckstop ID,Truckstop Name,Address,City,State,Rack ID,Retail Price\n"
        b"1,Caf\xe9,A,Tomah,WI,1,3.1\n"
    )

    with pytest.raises(CsvFormatError, match="UTF-8"):
        import_fuel_prices(path)


# --- duplicates --------------------------------------------------------------


def test_duplicate_ids_merge_into_one_station(sample_csv: Path) -> None:
    import_fuel_prices(sample_csv)

    station = FuelStation.objects.get(opis_id=20)
    assert station.retail_price == Decimal("3.799")
    assert station.max_retail_price == Decimal("3.999")
    assert station.price_observations == 3
    assert station.name == "PILOT TRAVEL CENTER #1243"  # most frequent spelling


def test_conflicting_duplicates_are_rejected_entirely(write_csv) -> None:
    path = write_csv([row(id="5", city="Tomah"), row(id="5", city="Sparta"), row(id="6")])

    result = import_fuel_prices(path)

    assert result.rejected_by_reason == {"conflicting_duplicate": 2}
    assert not FuelStation.objects.filter(opis_id=5).exists()
    assert FuelStation.objects.filter(opis_id=6).exists()


def test_invalid_row_does_not_discard_valid_duplicates(write_csv) -> None:
    path = write_csv([row(id="5", price="oops"), row(id="5", price="3.40")])

    result = import_fuel_prices(path)

    assert result.rejected_by_reason == {"invalid_price": 1}
    station = FuelStation.objects.get(opis_id=5)
    assert (station.retail_price, station.price_observations) == (Decimal("3.40"), 1)


def test_same_location_different_ids_are_separate_stations(write_csv) -> None:
    import_fuel_prices(write_csv([row(id="1", name="LOVES"), row(id="2", name="PILOT")]))

    assert FuelStation.objects.count() == 2


# --- re-import ----------------------------------------------------------------


def test_repeated_import_creates_no_duplicates(sample_csv: Path) -> None:
    import_fuel_prices(sample_csv)
    second = import_fuel_prices(sample_csv)

    assert (second.inserted, second.updated, second.unchanged) == (0, 0, 6)
    assert FuelStation.objects.count() == 6


def test_reimport_updates_changed_price(write_csv) -> None:
    import_fuel_prices(write_csv([row(price="3.25")]))
    result = import_fuel_prices(write_csv([row(price="3.15")]))

    assert (result.inserted, result.updated) == (0, 1)
    assert FuelStation.objects.get().retail_price == Decimal("3.15")


def test_reimport_with_new_city_clears_old_coordinates(write_csv) -> None:
    import_fuel_prices(write_csv([row()]))
    FuelStation.objects.update(
        latitude=43.98, longitude=-90.50, geolocation_accuracy=GeolocationAccuracy.CITY
    )

    import_fuel_prices(write_csv([row(city="Sparta")]))

    station = FuelStation.objects.get()
    assert station.geolocation_accuracy == GeolocationAccuracy.UNRESOLVED
    assert station.latitude is None and station.longitude is None


def test_reimport_with_price_change_keeps_coordinates(write_csv) -> None:
    import_fuel_prices(write_csv([row()]))
    FuelStation.objects.update(
        latitude=43.98, longitude=-90.50, geolocation_accuracy=GeolocationAccuracy.CITY
    )

    import_fuel_prices(write_csv([row(price="3.99")]))

    assert FuelStation.objects.get().latitude == 43.98


def test_stations_missing_from_new_file_are_kept_and_reported(write_csv) -> None:
    import_fuel_prices(write_csv([row(id="1"), row(id="2")]))
    result = import_fuel_prices(write_csv([row(id="1")]))

    assert result.existing_not_in_file == 1
    assert FuelStation.objects.count() == 2


# --- transactions -------------------------------------------------------------


def test_dry_run_writes_nothing(sample_csv: Path) -> None:
    result = import_fuel_prices(sample_csv, dry_run=True)

    assert result.inserted == 6
    assert FuelStation.objects.count() == 0


def test_failed_write_rolls_back_whole_import(write_csv) -> None:
    import_fuel_prices(write_csv([row(id="1", price="3.00")]))
    path = write_csv([row(id="1", price="3.50"), row(id="2")])

    with (
        patch.object(FuelStation.objects, "bulk_update", side_effect=IntegrityError("boom")),
        pytest.raises(IntegrityError),
    ):
        import_fuel_prices(path)

    # The insert of id=2 happened before the failing update and must be rolled back.
    assert list(FuelStation.objects.values_list("opis_id", flat=True)) == [1]
    assert FuelStation.objects.get().retail_price == Decimal("3.00")


# --- management command & reporting ------------------------------------------


def test_command_reports_counts(sample_csv: Path, sample_gazetteer: Path, settings) -> None:
    settings.GAZETTEER_PLACES_PATH = sample_gazetteer
    out = StringIO()

    call_command("import_fuel_prices", file=sample_csv, stdout=out)

    text = out.getvalue()
    for expected in (
        "CSV rows read:           9",
        "Skipped rows:            1",
        "Duplicate rows merged:   2",
        "Inserted:                6",
        "Resolved (city-level):   4",
        "non_us_station",
    ):
        assert expected in text


def test_command_dry_run_skips_geolocation(sample_csv: Path) -> None:
    out = StringIO()

    call_command("import_fuel_prices", file=sample_csv, dry_run=True, stdout=out)

    assert "DRY RUN" in out.getvalue()
    assert "Geolocation: skipped." in out.getvalue()
    assert FuelStation.objects.count() == 0


def test_command_turns_format_errors_into_command_error(tmp_path: Path) -> None:
    with pytest.raises(CommandError, match="not found"):
        call_command("import_fuel_prices", file=tmp_path / "missing.csv", stdout=StringIO())
