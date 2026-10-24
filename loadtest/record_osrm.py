"""Record real OSRM responses once, so load tests never hit the public demo server.

    uv run python loadtest/record_osrm.py        # ~15 requests at 1 req/s

Coordinates are resolved exactly as the app resolves them (offline gazetteer), and the
fixture is keyed by the exact URL coordinate segment the OSRM adapter will request.
"""

import gzip
import json
import os
import sys
import time
from pathlib import Path

import django
import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from fuel_route.infrastructure.geocoding import CoordinateGeocoder, GazetteerGeocoder, GeocoderChain  # noqa: E402
from loadtest.trips import TRIPS  # noqa: E402

OUT = Path(__file__).parent / "fixtures" / "osrm_routes.json.gz"
OSRM = "https://router.project-osrm.org/route/v1/driving/"
PARAMS = {"overview": "full", "geometries": "geojson", "steps": "false", "alternatives": "false"}


def main() -> None:
    resolver = GeocoderChain([CoordinateGeocoder(), GazetteerGeocoder()])
    fixtures = json.loads(gzip.decompress(OUT.read_bytes())) if OUT.exists() else {}
    for start, finish, *_ in TRIPS:
        a, b = resolver.resolve(start).point, resolver.resolve(finish).point
        key = f"{a[1]},{a[0]};{b[1]},{b[0]}"  # identical to OsrmRoutingProvider
        if key in fixtures:
            continue
        resp = requests.get(OSRM + key, params=PARAMS, timeout=30, headers={"User-Agent": "spotter-fuel-route/0.1"})
        resp.raise_for_status()
        fixtures[key] = resp.json()
        print(f"recorded {start} -> {finish}")
        time.sleep(1.1)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_bytes(gzip.compress(json.dumps(fixtures).encode()))
    print(f"{len(fixtures)} routes in {OUT}")


if __name__ == "__main__":
    main()
