"""Load the gazetteer and the OPIS price file, geocoding every station offline.

    uv run python manage.py load_fuel_data [--csv path/to/prices.csv]

Idempotent: both tables are replaced inside one transaction. Takes a few seconds and
makes no network calls; the per-request path never geocodes stations.
"""

import csv
import gzip
import hashlib
from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from fuel_route.infrastructure.names import US_STATES, place_key
from fuel_route.models import FuelDataset, FuelStation, Place


class Command(BaseCommand):
    help = "Load US places and fuel stations (with offline geocoding) into the database."

    def add_arguments(self, parser):
        parser.add_argument("--csv", type=Path, default=settings.DATA_DIR / "fuel-prices-for-be-assessment.csv")
        parser.add_argument("--places", type=Path, default=settings.DATA_DIR / "us_places.csv.gz")
        parser.add_argument("--overrides", type=Path, default=settings.DATA_DIR / "city_overrides.csv")

    def handle(self, *args, csv: Path, places: Path, overrides: Path, **options):
        for p in (csv, places):
            if not p.exists():
                raise CommandError(f"Missing data file: {p}")

        place_rows = self._read_places(places, overrides)
        coords = {(r.state, r.key): (r.lat, r.lng) for r in place_rows}
        stations, skipped_foreign, unresolved = self._read_stations(csv, coords)

        with transaction.atomic():
            Place.objects.all().delete()
            Place.objects.bulk_create(place_rows, batch_size=5000)
            FuelStation.objects.all().delete()
            FuelStation.objects.bulk_create(stations, batch_size=2000)
            # Bumping the version is what makes running web workers pick up the new data.
            version = hashlib.sha256(csv.read_bytes()).hexdigest()
            FuelDataset.objects.update_or_create(pk=1, defaults={"version": version, "stations": len(stations)})

        self.stdout.write(self.style.SUCCESS(f"Loaded {len(place_rows)} places and {len(stations)} stations."))
        self.stdout.write(f"Skipped {skipped_foreign} rows outside the USA (Canadian provinces).")
        if unresolved:
            sample = ", ".join(sorted(unresolved)[:10])
            self.stdout.write(self.style.WARNING(f"{len(unresolved)} US cities not geocoded, e.g. {sample}"))

    @staticmethod
    def _read_places(places: Path, overrides: Path) -> list[Place]:
        rows: dict[tuple[str, str], Place] = {}
        # Overrides first: they win over gazetteer entries with the same key.
        for path in [overrides, places] if overrides.exists() else [places]:
            opener = gzip.open if path.suffix == ".gz" else open
            with opener(path, "rt", newline="") as fh:
                for r in csv.DictReader(fh):
                    rows.setdefault(
                        (r["state"], r["key"]),
                        Place(state=r["state"], key=r["key"], name=r["name"], lat=float(r["lat"]), lng=float(r["lng"])),
                    )
        return list(rows.values())

    @staticmethod
    def _read_stations(path: Path, coords: dict) -> tuple[list[FuelStation], int, set[str]]:
        by_id: dict[int, FuelStation] = {}
        skipped_foreign = 0
        unresolved: set[str] = set()
        with path.open(newline="") as fh:
            for r in csv.DictReader(fh):
                r = {k: (v or "").strip() for k, v in r.items()}
                state, city = r["State"].upper(), r["City"]
                if state not in US_STATES:
                    skipped_foreign += 1
                    continue
                try:
                    opis_id, price = int(r["OPIS Truckstop ID"]), Decimal(r["Retail Price"])
                except (ValueError, InvalidOperation):
                    continue
                # The file repeats a station once per rack/price; a driver pays the lowest posted price.
                if opis_id in by_id and by_id[opis_id].price <= price:
                    continue
                point = coords.get((state, place_key(city)))
                if point is None:
                    unresolved.add(f"{city}, {state}")
                    continue
                by_id[opis_id] = FuelStation(
                    opis_id=opis_id,
                    name=r["Truckstop Name"],
                    address=r["Address"],
                    city=city.title(),
                    state=state,
                    rack_id=int(r["Rack ID"]) if r["Rack ID"].isdigit() else None,
                    price=price.quantize(Decimal("0.0001")),
                    lat=point[0],
                    lng=point[1],
                )
        return list(by_id.values()), skipped_foreign, unresolved
