from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.fuel.geolocation import Gazetteer, GazetteerError, geolocate_stations
from apps.fuel.importer import CsvFormatError, ImportResult, RowIssue, import_fuel_prices
from apps.fuel.management.commands.geolocate_stations import write_geolocation_report


class Command(BaseCommand):
    help = "Import the fuel-price CSV into FuelStation rows, then geolocate new stations offline."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--file", type=Path, default=None, help="CSV path (default: settings).")
        parser.add_argument(
            "--dry-run", action="store_true", help="Validate and report; write nothing."
        )
        parser.add_argument(
            "--skip-geolocation", action="store_true", help="Do not geolocate unresolved stations."
        )
        parser.add_argument(
            "--show-issues",
            type=int,
            default=5,
            metavar="N",
            help="Rejected/skipped rows to list per reason.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        path: Path = options["file"] or settings.FUEL_PRICES_CSV_PATH
        started = time.perf_counter()
        try:
            result = import_fuel_prices(path, dry_run=options["dry_run"])
        except CsvFormatError as exc:
            raise CommandError(str(exc)) from exc
        elapsed = time.perf_counter() - started
        self._write_import_report(path, result, elapsed, options["show_issues"])

        if options["dry_run"] or options["skip_geolocation"]:
            self.stdout.write("Geolocation: skipped.")
            return
        started = time.perf_counter()
        try:
            gazetteer = Gazetteer.from_file(settings.GAZETTEER_PLACES_PATH)
        except GazetteerError as exc:
            raise CommandError(str(exc)) from exc
        geo = geolocate_stations(gazetteer)
        write_geolocation_report(self.stdout, geo, time.perf_counter() - started)

    def _write_import_report(self, path: Path, r: ImportResult, elapsed: float, show: int) -> None:
        mode = " (DRY RUN — nothing written)" if r.dry_run else ""
        out = self.stdout
        out.write(self.style.MIGRATE_HEADING(f"Fuel price import{mode}"))
        out.write(f"  File:                    {path}")
        out.write(f"  CSV rows read:           {r.total_rows}")
        out.write(f"  Valid rows:              {r.valid_rows}")
        out.write(f"  Rejected rows:           {len(r.rejected)}  {r.rejected_by_reason or ''}")
        out.write(f"  Skipped rows:            {len(r.skipped)}  {r.skipped_by_reason or ''}")
        out.write(f"  Warnings:                {len(r.warnings)}  {r.warnings_by_reason or ''}")
        out.write(f"  Duplicate rows merged:   {r.duplicate_rows_merged}")
        out.write(f"  Stations in file:        {r.stations_in_file}")
        out.write(f"  Inserted:                {r.inserted}")
        out.write(f"  Updated:                 {r.updated}")
        out.write(f"  Unchanged:               {r.unchanged}")
        out.write(f"  In DB but not in file:   {r.existing_not_in_file} (kept, not deleted)")
        out.write(f"  Import time:             {elapsed:.2f}s")
        for title, issues in (("Rejected", r.rejected), ("Skipped", r.skipped)):
            self._write_examples(title, issues, show)

    def _write_examples(self, title: str, issues: list[RowIssue], show: int) -> None:
        if show <= 0 or not issues:
            return
        shown: dict[str, int] = {}
        self.stdout.write(f"  {title} examples:")
        for issue in issues:
            if shown.get(issue.reason, 0) >= show:
                continue
            shown[issue.reason] = shown.get(issue.reason, 0) + 1
            self.stdout.write(
                f"    line {issue.line} id={issue.opis_id} [{issue.reason}] {issue.detail}"
            )
