"""Read-only fingerprint of the fuel-station data, for comparing local and production.

Run it against each database and compare the outputs line by line. It never writes: on
PostgreSQL the work runs in a ``READ ONLY`` transaction and on SQLite with ``query_only``.
It never prints the connection URL, host, user or password.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import connection, transaction

from apps.fuel.geolocation import Gazetteer, GazetteerError
from apps.fuel.models import FuelStation, GeolocationAccuracy

# The three stations reported as unresolved in production (OPIS IDs from the employer CSV).
EXAMPLE_OPIS_IDS = (253, 256, 257)


def file_sha256(path: Path) -> str:
    if not path.is_file():
        return "MISSING"
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return f"{digest.hexdigest()}  ({path.stat().st_size:,} bytes)"


def _num(value: float | None, places: int) -> str:
    return "" if value is None else f"{value:.{places}f}"


@contextmanager
def read_only() -> Iterator[None]:
    """Run the block in a transaction the database itself refuses to write in."""
    try:
        with transaction.atomic():
            with connection.cursor() as cursor:
                if connection.vendor == "postgresql":
                    cursor.execute("SET TRANSACTION READ ONLY")
                elif connection.vendor == "sqlite":
                    cursor.execute("PRAGMA query_only = ON")
            yield
            transaction.set_rollback(True)
    finally:
        if connection.vendor == "sqlite":  # a connection setting, not part of the transaction
            with connection.cursor() as cursor:
                cursor.execute("PRAGMA query_only = OFF")


class Command(BaseCommand):
    help = "Read-only report of fuel-station counts, fingerprints and example records."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--opis-id",
            type=int,
            action="append",
            dest="opis_ids",
            help=f"Station to print (repeatable; default {', '.join(map(str, EXAMPLE_OPIS_IDS))}).",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        try:
            gazetteer = Gazetteer.from_file(settings.GAZETTEER_PLACES_PATH)
        except GazetteerError as exc:
            raise CommandError(str(exc)) from exc
        with read_only():
            self._report(gazetteer, options["opis_ids"] or list(EXAMPLE_OPIS_IDS))

    def _report(self, gazetteer: Gazetteer, opis_ids: list[int]) -> None:
        out = self.stdout.write
        out(self.style.MIGRATE_HEADING("RouteFuel fuel-station data report (read-only)"))
        out("Database")
        out(f"  Engine:                  {connection.vendor} {self._server_version()}")
        out(f"  Database name:           {Path(str(connection.settings_dict['NAME'])).name}")
        out(f"  Encrypted connection:    {self._tls()}")

        rows = list(
            FuelStation.objects.order_by("opis_id").values_list(
                "opis_id", "name", "address", "city", "state", "rack_id",
                "retail_price", "max_retail_price", "price_observations",
                "latitude", "longitude", "geolocation_accuracy", "geolocation_source",
                "location_uncertainty_miles",
            )
        )  # fmt: skip
        located = [r for r in rows if r[9] is not None and r[10] is not None]
        unresolved = [r for r in rows if r[11] == GeolocationAccuracy.UNRESOLVED]
        inconsistent = sum(
            1 for r in rows if (r[11] == GeolocationAccuracy.UNRESOLVED) != (r[9] is None)
        )
        out("Stations")
        out(f"  Total:                   {len(rows)}")
        out(f"  With coordinates:        {len(located)}")
        out(f"  Unresolved:              {len(unresolved)}")
        out(f"  Accuracy:                {dict(sorted(Counter(r[11] for r in rows).items()))}")
        out(f"  Source:                  {dict(sorted(Counter(r[12] for r in rows).items()))}")
        out(f"  Inconsistent rows:       {inconsistent}  (accuracy disagrees with coordinates)")
        if rows:
            stamps = FuelStation.objects.order_by("updated_at").values_list("updated_at", flat=True)
            out(f"  Last updated (UTC):      {stamps.last():%Y-%m-%d %H:%M:%S}")

        # Engine-independent canonical text, so SQLite and PostgreSQL hash identically.
        data = "\n".join(
            "|".join([str(r[0]), r[1], r[2], r[3], r[4], str(r[5]), f"{r[6]:.3f}",
                      f"{r[7]:.3f}", str(r[8])])
            for r in rows
        )  # fmt: skip
        geo = "\n".join(
            "|".join([str(r[0]), _num(r[9], 6), _num(r[10], 6), r[11], r[12], _num(r[13], 1)])
            for r in rows
        )
        out("Fingerprints (identical on both databases = identical data)")
        out(f"  Station data:            {hashlib.sha256(data.encode()).hexdigest()[:16]}")
        out(f"  Geolocation:             {hashlib.sha256(geo.encode()).hexdigest()[:16]}")

        out("Reference files on this machine")
        out(f"  Fuel-price CSV:          {file_sha256(settings.FUEL_PRICES_CSV_PATH)}")
        out(f"  Census Gazetteer:        {file_sha256(settings.GAZETTEER_PLACES_PATH)}")

        resolvable = differing = 0
        for r in rows:
            place = gazetteer.lookup(r[3], r[4]).place
            if r[11] == GeolocationAccuracy.UNRESOLVED and place is not None:
                resolvable += 1
            elif r[11] == GeolocationAccuracy.CITY and (
                place is None or (_num(r[9], 6), _num(r[10], 6))
                != (_num(place.latitude, 6), _num(place.longitude, 6))
            ):
                differing += 1
        out("Gazetteer re-check (in memory, nothing written)")
        out(f"  Unresolved the gazetteer resolves: {resolvable}  (0 when fully geolocated)")
        out(f"  City-level points that differ:     {differing}  (0 expected)")

        out("Example stations")
        by_id = {r[0]: r for r in rows}
        for opis_id in opis_ids:
            r = by_id.get(opis_id)
            if r is None:
                out(f"  {opis_id}: not in this database")
                continue
            place = gazetteer.lookup(r[3], r[4]).place
            expected = f"{place.latitude:.6f}, {place.longitude:.6f}" if place else "unresolved"
            out(
                f"  {opis_id} {r[1]}, {r[3]}, {r[4]}: lat={_num(r[9], 6) or '-'} "
                f"lng={_num(r[10], 6) or '-'} accuracy={r[11]} "
                f"source={r[12] or '-'} (gazetteer: {expected})"
            )

    @staticmethod
    def _server_version() -> str:
        if connection.vendor == "postgresql":
            with connection.cursor() as cursor:
                cursor.execute("SHOW server_version")
                return f"(server {cursor.fetchone()[0].split()[0]})"
        if connection.vendor == "sqlite":
            import sqlite3

            return f"(SQLite {sqlite3.sqlite_version})"
        return ""

    @staticmethod
    def _tls() -> str:
        if connection.vendor != "postgresql":
            return "n/a (local file)"
        with connection.cursor() as cursor:
            cursor.execute("SELECT ssl FROM pg_stat_ssl WHERE pid = pg_backend_pid()")
            row = cursor.fetchone()
        return "yes (TLS)" if row and row[0] else "NO"
