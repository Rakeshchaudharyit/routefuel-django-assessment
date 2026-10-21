"""Load the employer fuel-price CSV into ``FuelStation`` rows.

Pipeline: read → validate each row → merge rows that share an OPIS ID → upsert.

Duplicate policy (see docs/architecture.md):
* One station per OPIS ID.
* Rows sharing an ID must agree on address, city, state and rack ID. If they do not,
  every row for that ID is rejected as ``conflicting_duplicate`` rather than guessed.
* ``retail_price`` is the lowest listed price; ``max_retail_price`` and
  ``price_observations`` record the spread so nothing is hidden.
* ``name`` is the most frequent spelling (first seen wins ties).
"""

from __future__ import annotations

import csv
import re
from collections import Counter
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from pathlib import Path

from django.db import transaction
from django.utils import timezone

from apps.fuel.constants import (
    CANADIAN_PROVINCE_CODES,
    MAX_RETAIL_PRICE,
    MIN_RETAIL_PRICE,
    PRICE_DECIMAL_PLACES,
    US_STATE_CODES,
)
from apps.fuel.models import FuelStation, GeolocationAccuracy, GeolocationSource

COL_ID = "OPIS Truckstop ID"
COL_NAME = "Truckstop Name"
COL_ADDRESS = "Address"
COL_CITY = "City"
COL_STATE = "State"
COL_RACK = "Rack ID"
COL_PRICE = "Retail Price"
REQUIRED_COLUMNS = (COL_ID, COL_NAME, COL_ADDRESS, COL_CITY, COL_STATE, COL_RACK, COL_PRICE)

MAX_POSITIVE_INT = 2_147_483_647  # PositiveIntegerField limit across databases
_DIGITS = re.compile(r"[0-9]+")
_HAS_ALNUM = re.compile(r"[A-Za-z0-9]")
BULK_BATCH_SIZE = 500


class CsvFormatError(Exception):
    """The file cannot be imported at all (missing, unreadable, wrong columns)."""


class Reason(StrEnum):
    MALFORMED_ROW = "malformed_row"
    MISSING_FIELD = "missing_field"
    INVALID_ID = "invalid_id"
    INVALID_RACK_ID = "invalid_rack_id"
    INVALID_STATE = "invalid_state"
    INVALID_PRICE = "invalid_price"
    CONFLICTING_DUPLICATE = "conflicting_duplicate"
    NON_US_STATION = "non_us_station"
    INCOMPLETE_ADDRESS = "incomplete_address"


@dataclass(frozen=True)
class RowIssue:
    line: int
    opis_id: str
    reason: Reason
    detail: str


@dataclass(frozen=True)
class ParsedRow:
    line: int
    opis_id: int
    name: str
    address: str
    city: str
    state: str
    rack_id: int
    price: Decimal


@dataclass(frozen=True)
class StationRecord:
    opis_id: int
    name: str
    address: str
    city: str
    state: str
    rack_id: int
    retail_price: Decimal
    max_retail_price: Decimal
    price_observations: int


@dataclass
class ImportResult:
    total_rows: int = 0
    valid_rows: int = 0
    duplicate_rows_merged: int = 0
    stations_in_file: int = 0
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0
    existing_not_in_file: int = 0
    dry_run: bool = False
    rejected: list[RowIssue] = field(default_factory=list)
    skipped: list[RowIssue] = field(default_factory=list)
    warnings: list[RowIssue] = field(default_factory=list)

    @staticmethod
    def _by_reason(issues: list[RowIssue]) -> dict[str, int]:
        return dict(Counter(issue.reason.value for issue in issues).most_common())

    @property
    def rejected_by_reason(self) -> dict[str, int]:
        return self._by_reason(self.rejected)

    @property
    def skipped_by_reason(self) -> dict[str, int]:
        return self._by_reason(self.skipped)

    @property
    def warnings_by_reason(self) -> dict[str, int]:
        return self._by_reason(self.warnings)


# ---------------------------------------------------------------------------
# Parsing & validation
# ---------------------------------------------------------------------------


def normalize_text(value: str) -> str:
    """Trim and collapse internal whitespace."""
    return " ".join(value.split())


def _parse_positive_int(raw: str) -> int | None:
    if not _DIGITS.fullmatch(raw):
        return None
    value = int(raw)
    return value if 0 < value <= MAX_POSITIVE_INT else None


def parse_price(raw: str) -> Decimal:
    """Parse a USD/gallon price exactly. Raises ``ValueError`` with a reason."""
    try:
        price = Decimal(raw)
    except InvalidOperation as exc:
        raise ValueError(f"not a number: {raw!r}") from exc
    if not price.is_finite():
        raise ValueError(f"not a finite number: {raw!r}")
    exponent = price.as_tuple().exponent
    if isinstance(exponent, int) and -exponent > PRICE_DECIMAL_PLACES:
        raise ValueError(f"more than {PRICE_DECIMAL_PLACES} decimal places: {raw!r}")
    if not MIN_RETAIL_PRICE <= price <= MAX_RETAIL_PRICE:
        raise ValueError(f"outside {MIN_RETAIL_PRICE}-{MAX_RETAIL_PRICE} USD/gal: {raw!r}")
    return price


def parse_row(line: int, raw: dict[str | None, str | list[str] | None]) -> ParsedRow | RowIssue:
    """Validate one CSV row. Returns the parsed row, or the issue that stops it."""
    raw_id = raw.get(COL_ID)
    id_text = raw_id.strip() if isinstance(raw_id, str) else ""

    # csv.DictReader stores surplus cells under the None key and fills missing cells with None.
    if None in raw or any(raw.get(col) is None for col in REQUIRED_COLUMNS):
        return RowIssue(line, id_text, Reason.MALFORMED_ROW, "wrong number of columns")

    values = {col: normalize_text(str(raw[col])) for col in REQUIRED_COLUMNS}
    missing = [
        col
        for col in (COL_ID, COL_NAME, COL_CITY, COL_STATE, COL_RACK, COL_PRICE)
        if not values[col]
    ]
    if missing:
        return RowIssue(line, id_text, Reason.MISSING_FIELD, f"missing {', '.join(missing)}")

    opis_id = _parse_positive_int(values[COL_ID])
    if opis_id is None:
        return RowIssue(
            line, id_text, Reason.INVALID_ID, f"not a positive integer: {values[COL_ID]!r}"
        )

    state = values[COL_STATE].upper()
    if state in CANADIAN_PROVINCE_CODES:
        return RowIssue(line, id_text, Reason.NON_US_STATION, f"Canadian province {state}")
    if state not in US_STATE_CODES:
        return RowIssue(
            line, id_text, Reason.INVALID_STATE, f"unknown state code {values[COL_STATE]!r}"
        )

    rack_id = _parse_positive_int(values[COL_RACK])
    if rack_id is None:
        return RowIssue(
            line, id_text, Reason.INVALID_RACK_ID, f"not a positive integer: {values[COL_RACK]!r}"
        )

    try:
        price = parse_price(values[COL_PRICE])
    except ValueError as exc:
        return RowIssue(line, id_text, Reason.INVALID_PRICE, str(exc))

    address = values[COL_ADDRESS] if _HAS_ALNUM.search(values[COL_ADDRESS]) else ""
    return ParsedRow(
        line=line,
        opis_id=opis_id,
        name=values[COL_NAME],
        address=address,
        city=values[COL_CITY],
        state=state,
        rack_id=rack_id,
        price=price,
    )


def read_rows(path: Path) -> tuple[list[ParsedRow], ImportResult]:
    """Read and validate every row. Raises ``CsvFormatError`` if the file is unusable."""
    result = ImportResult()
    parsed: list[ParsedRow] = []
    try:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            header = [normalize_text(col) for col in (reader.fieldnames or [])]
            absent = [col for col in REQUIRED_COLUMNS if col not in header]
            if absent:
                raise CsvFormatError(f"CSV is missing required columns: {', '.join(absent)}")
            reader.fieldnames = header
            for raw in reader:
                result.total_rows += 1
                outcome = parse_row(reader.line_num, raw)
                if isinstance(outcome, ParsedRow):
                    parsed.append(outcome)
                    if not outcome.address:
                        result.warnings.append(
                            RowIssue(
                                outcome.line,
                                str(outcome.opis_id),
                                Reason.INCOMPLETE_ADDRESS,
                                "address is blank",
                            )
                        )
                elif outcome.reason is Reason.NON_US_STATION:
                    result.skipped.append(outcome)
                else:
                    result.rejected.append(outcome)
    except FileNotFoundError as exc:
        raise CsvFormatError(f"CSV file not found: {path}") from exc
    except UnicodeDecodeError as exc:
        raise CsvFormatError(f"CSV is not valid UTF-8: {exc}") from exc
    except csv.Error as exc:
        raise CsvFormatError(f"CSV could not be parsed: {exc}") from exc
    return parsed, result


# ---------------------------------------------------------------------------
# Duplicate merging
# ---------------------------------------------------------------------------


def _location_key(row: ParsedRow) -> tuple[str, str, str, int]:
    return (row.address.casefold(), row.city.casefold(), row.state, row.rack_id)


def merge_duplicates(rows: list[ParsedRow]) -> tuple[list[StationRecord], list[RowIssue], int]:
    """Collapse rows per OPIS ID. Returns (records, conflict issues, rows merged away)."""
    groups: dict[int, list[ParsedRow]] = {}
    for row in rows:
        groups.setdefault(row.opis_id, []).append(row)

    records: list[StationRecord] = []
    conflicts: list[RowIssue] = []
    merged = 0
    for opis_id, group in groups.items():
        if len({_location_key(row) for row in group}) > 1:
            lines = ", ".join(str(row.line) for row in group)
            conflicts.extend(
                RowIssue(
                    row.line,
                    str(opis_id),
                    Reason.CONFLICTING_DUPLICATE,
                    f"location differs across lines {lines}",
                )
                for row in group
            )
            continue
        merged += len(group) - 1
        first = group[0]
        prices = [row.price for row in group]
        records.append(
            StationRecord(
                opis_id=opis_id,
                name=Counter(row.name for row in group).most_common(1)[0][0],
                address=first.address,
                city=first.city,
                state=first.state,
                rack_id=first.rack_id,
                retail_price=min(prices),
                max_retail_price=max(prices),
                price_observations=len(group),
            )
        )
    return records, conflicts, merged


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

_DATA_FIELDS = (
    "name",
    "address",
    "city",
    "state",
    "rack_id",
    "retail_price",
    "max_retail_price",
    "price_observations",
)
_LOCATION_FIELDS = ("address", "city", "state")
_GEO_FIELDS = (
    "latitude",
    "longitude",
    "geolocation_source",
    "geolocation_accuracy",
    "location_uncertainty_miles",
)


def _reset_geolocation(station: FuelStation) -> None:
    station.latitude = None
    station.longitude = None
    station.geolocation_source = GeolocationSource.NONE
    station.geolocation_accuracy = GeolocationAccuracy.UNRESOLVED
    station.location_uncertainty_miles = None


def upsert_stations(records: list[StationRecord], result: ImportResult) -> None:
    """Insert new stations and update changed ones in bulk (caller supplies the transaction)."""
    existing = FuelStation.objects.in_bulk([r.opis_id for r in records], field_name="opis_id")
    now = timezone.now()
    to_create: list[FuelStation] = []
    to_update: list[FuelStation] = []

    for record in records:
        station = existing.get(record.opis_id)
        if station is None:
            to_create.append(
                FuelStation(opis_id=record.opis_id, **{f: getattr(record, f) for f in _DATA_FIELDS})
            )
            continue
        changed = [f for f in _DATA_FIELDS if getattr(station, f) != getattr(record, f)]
        if not changed:
            result.unchanged += 1
            continue
        if any(f in changed for f in _LOCATION_FIELDS):
            # Old coordinates belonged to the old location; never keep them.
            _reset_geolocation(station)
        for f in changed:
            setattr(station, f, getattr(record, f))
        station.updated_at = now
        to_update.append(station)

    FuelStation.objects.bulk_create(to_create, batch_size=BULK_BATCH_SIZE)
    FuelStation.objects.bulk_update(
        to_update, [*_DATA_FIELDS, *_GEO_FIELDS, "updated_at"], batch_size=BULK_BATCH_SIZE
    )
    result.inserted = len(to_create)
    result.updated = len(to_update)
    result.existing_not_in_file = FuelStation.objects.count() - len(existing) - len(to_create)


def import_fuel_prices(path: Path, *, dry_run: bool = False) -> ImportResult:
    """Validate, merge and upsert the CSV atomically. ``dry_run`` rolls back all writes."""
    rows, result = read_rows(path)
    records, conflicts, merged = merge_duplicates(rows)

    result.rejected.extend(conflicts)
    result.valid_rows = len(rows) - len(conflicts)
    result.duplicate_rows_merged = merged
    result.stations_in_file = len(records)
    result.dry_run = dry_run

    with transaction.atomic():
        upsert_stations(records, result)
        if dry_run:
            transaction.set_rollback(True)
    return result
