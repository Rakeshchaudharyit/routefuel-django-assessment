from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser, OutputWrapper

from apps.fuel.geolocation import Gazetteer, GazetteerError, GeolocationResult, geolocate_stations
from apps.fuel.models import FuelStation, GeolocationAccuracy


def write_geolocation_report(out: OutputWrapper, r: GeolocationResult, elapsed: float) -> None:
    out.write("Geolocation (offline Census Gazetteer, city-level):")
    out.write(f"  Stations considered:     {r.considered}")
    out.write(f"  Resolved (city-level):   {r.resolved}")
    out.write(f"  Unresolved, ambiguous:   {r.ambiguous}")
    out.write(f"  Unresolved, not found:   {r.not_found}")
    out.write(f"  Distinct city lookups:   {r.distinct_places_looked_up}")
    out.write(f"  Geolocation time:        {elapsed:.2f}s")
    if r.unresolved_examples:
        out.write("  Unresolved examples:     " + "; ".join(r.unresolved_examples))
    totals = {
        accuracy.label: FuelStation.objects.filter(geolocation_accuracy=accuracy).count()
        for accuracy in GeolocationAccuracy
    }
    out.write(f"  Database totals:         {totals}")


class Command(BaseCommand):
    help = "Assign approximate city-level coordinates to stations from the local Census Gazetteer."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--gazetteer", type=Path, default=None, help="Gazetteer path (default: settings)."
        )
        parser.add_argument(
            "--force", action="store_true", help="Recompute existing city-level coordinates too."
        )

    def handle(self, *args: Any, **options: Any) -> None:
        path: Path = options["gazetteer"] or settings.GAZETTEER_PLACES_PATH
        started = time.perf_counter()
        try:
            gazetteer = Gazetteer.from_file(path)
        except GazetteerError as exc:
            raise CommandError(str(exc)) from exc
        result = geolocate_stations(gazetteer, force=options["force"])
        write_geolocation_report(self.stdout, result, time.perf_counter() - started)
