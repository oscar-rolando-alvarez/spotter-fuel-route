"""One-off: geocode the station cities the Census gazetteer can't resolve.

About 3% of US stations sit in unincorporated communities ("Ruther Glen, VA",
"Breezewood, PA") that are neither Census places nor county subdivisions. This
script resolves them once through Nominatim (respecting its 1 req/s policy) and
writes data/city_overrides.csv, which is committed. Runtime never calls it.

    uv run python scripts/resolve_unmatched_cities.py
"""

import csv
import gzip
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fuel_route.services.names import US_STATES, place_key  # noqa: E402

DATA = ROOT / "data"
NOMINATIM = "https://nominatim.openstreetmap.org/search"
HEADERS = {"User-Agent": "spotter-fuel-route/0.1 (offline station geocoding)"}


def main() -> None:
    with gzip.open(DATA / "us_places.csv.gz", "rt") as f:
        known = {(r["state"], r["key"]) for r in csv.DictReader(f)}
    with open(DATA / "fuel-prices-for-be-assessment.csv", newline="") as f:
        cities = sorted(
            {
                (r["City"].strip(), r["State"].strip())
                for r in csv.DictReader(f)
                if r["State"].strip() in US_STATES and (r["State"].strip(), place_key(r["City"])) not in known
            }
        )

    rows, missing = [], []
    for city, state in cities:
        resp = requests.get(
            NOMINATIM,
            params={"city": city, "state": US_STATES[state], "countrycodes": "us", "format": "jsonv2", "limit": 1},
            headers=HEADERS,
            timeout=15,
        )
        resp.raise_for_status()
        hits = resp.json()
        if hits:
            rows.append([state, place_key(city), city, hits[0]["lat"], hits[0]["lon"]])
        else:
            missing.append(f"{city}, {state}")
        time.sleep(1.1)

    with open(DATA / "city_overrides.csv", "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["state", "key", "name", "lat", "lng"])
        writer.writerows(rows)
    print(f"resolved {len(rows)}/{len(cities)}; unresolved: {missing}")


if __name__ == "__main__":
    main()
